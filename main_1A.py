import pymupdf
import json
import pytesseract
from PIL import Image
import io
import os
import re
from collections import Counter


class pdf_outline_extractor:

    def __init__(self, pdf_doc, max_heading_word_percentage=0.10): # Corrected __init__

        self.doc = pdf_doc
        self.max_heading_word_percent = max_heading_word_percentage
        self.total_words_in_doc = 0
        self.all_blocks_data = []
        self.body_style = {}
        self.heading_font_sizes = []

    def get_text_alignment(self, line_bbox, page_width):
        x0, y0, x1, y1 = line_bbox
        line_width = x1 - x0
        center_position = (x0 + x1) / 2

        if (page_width * 0.4) < center_position < (page_width * 0.6):
            if line_width < (page_width * 0.8):
                return "center"
        if x0 < (page_width * 0.15):
            return "left"
        if x1 > (page_width * 0.85):
            return "right"
        return "left"

    def _get_underline_bboxes(self):
        self.underline_bboxes = {}
        for page_idx in range(self.doc.page_count): # Renamed loop variable to avoid conflict
            self.underline_bboxes[page_idx + 1] = []
            drawings = self.doc[page_idx].get_drawings()
            for path in drawings:

                if path['rect'].height < 2 and path['rect'].width > 5:
                    self.underline_bboxes[page_idx + 1].append(path['rect'])

    def step_1_extract_features(self):
        header_footer_candidates = Counter()
        page_count = self.doc.page_count
        for page_idx in range(page_count): # Renamed loop variable
            page = self.doc[page_idx] # Changed page_num to page for clarity as it's a PyMuPDF page object
            self.total_words_in_doc += len(page.get_text("words"))
            page_height = page.rect.height
            page_width = page.rect.width
            header_zone = page_height * 0.12
            footer_zone = page_height * 0.88

            blocks = page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)["blocks"]
            for block in blocks:
                for line_step1 in block.get("lines", []):
                    spans = line_step1.get("spans")
                    if not spans:
                        continue

                    line_text = None
                    main_span = None

                    sorted_spans = sorted(spans, key=lambda s: s['size'], reverse=True)

                    for span in sorted_spans:

                        if len(span['text'].strip()) > 3:
                            main_span = span

                            line_text = span['text'].strip()
                            break

                    if not main_span:
                        continue

                    is_underlined = False
                    line_bbox = pymupdf.Rect(line_step1["bbox"])
                    for u_bbox in self.underline_bboxes.get(page_idx + 1, []): # Use page_idx

                        if abs(u_bbox.y0 - line_bbox.y1) < 2 and \
                                max(line_bbox.x0, u_bbox.x0) < min(line_bbox.x1, u_bbox.x1):
                            is_underlined = True
                            break

                    block_info = {
                        "text": line_text,
                        "font_size": round(main_span["size"]),
                        "font_name": main_span["font"],
                        "color": main_span["color"],
                        "alignment": self.get_text_alignment(line_step1["bbox"], page_width),
                        "page_num": page_idx + 1, # Changed to page_num
                        "y_coord": line_step1["bbox"][1],
                        "length": len(line_text),
                        "is_underlined": is_underlined
                    }
                    self.all_blocks_data.append(block_info)

                    is_header = line_step1["bbox"][1] < header_zone
                    is_footer = line_step1["bbox"][3] > footer_zone
                    if is_header or is_footer:
                        normalized_text = re.sub(r'\d+', '', line_text).strip().lower()
                        if len(normalized_text) > 4:
                            header_footer_candidates[normalized_text] += 1

        self.header_footer_blacklist = {
            text for text, count in header_footer_candidates.items()
            if count > page_count / 2 and page_count > 1
        }

    def step_2_analyze_styles(self):
        filtered_blocks = [
            b for b in self.all_blocks_data
            if re.sub(r'\d+', '', b["text"]).strip().lower() not in self.header_footer_blacklist
        ]
        self.all_blocks_data = filtered_blocks

        if not self.all_blocks_data:
            return

        font_sizes = Counter(b["font_size"] for b in self.all_blocks_data)
        font_colors = Counter(b["color"] for b in self.all_blocks_data)

        body_font_size = font_sizes.most_common(1)[0][0]
        body_font_color = font_colors.most_common(1)[0][0]
        self.body_style = {"size": body_font_size, "color": body_font_color}

        unique_sizes = sorted([s for s in font_sizes if s > body_font_size], reverse=True)
        self.heading_font_sizes = unique_sizes

    def step_3_score_and_classify_headings(self, allow_body_size=False):

        candidate_headings = []
        if not self.body_style:
            return []

        for block in self.all_blocks_data:
            score = 0

            is_heading_sized = block["font_size"] > self.body_style.get("size", 0)
            is_body_sized_candidate = allow_body_size and block["font_size"] == self.body_style.get("size", 0)

            if not (is_heading_sized or is_body_sized_candidate):
                continue

            if is_heading_sized:
                score += 2
            if "bold" in block["font_name"].lower():
                score += 2
            if block["alignment"] == "center":
                score += 1
            if block["color"] != self.body_style.get("color"):
                score += 1
            if block.get("is_underlined"):
                score += 1
            if block["text"].isupper() and len(block["text"].split()) > 1:
                score += 1

            if block["length"] < 3:
                score -= 3
            if block["length"] > 100:
                score -= 1

            if score >= 2 and any(c.isalpha() for c in block["text"]):

                if is_heading_sized:
                    level_index = self.heading_font_sizes.index(block["font_size"])
                    block["level"] = f"H{level_index + 1}"

                elif is_body_sized_candidate:

                    block["level"] = f"H{len(self.heading_font_sizes) + 1}"

                block["score"] = score
                candidate_headings.append(block)

        return candidate_headings

    def step_4_refine_with_word_count(self, candidates):

        if not candidates or self.total_words_in_doc == 0:
            return []

        final_headings = list(candidates)

        def get_heading_stats(headings):
            word_count = sum(len(h["text"].split()) for h in headings)
            percent = (word_count / self.total_words_in_doc) if self.total_words_in_doc > 0 else 0
            return word_count, percent

        heading_word_count, heading_percent = get_heading_stats(final_headings)

        while heading_percent > self.max_heading_word_percent and final_headings:

            present_levels = sorted(
                list(set(h['level'] for h in final_headings)),
                key=lambda level: int(level[1:]),
                reverse=True
            )

            if not present_levels:
                break

            lowest_level_str = present_levels[0]

            headings_at_lowest_level = [
                h for h in final_headings if h['level'] == lowest_level_str
            ]

            if not headings_at_lowest_level:
                break

            min_score_at_level = min(h['score'] for h in headings_at_lowest_level)

            batch_to_remove = [
                h for h in headings_at_lowest_level if h['score'] == min_score_at_level
            ]

            if not batch_to_remove:
                break

            ids_to_remove = {id(h) for h in batch_to_remove}
            final_headings = [h for h in final_headings if id(h) not in ids_to_remove]

            heading_word_count, heading_percent = get_heading_stats(final_headings)

        final_headings.sort(key=lambda x: (x["page_num"], x["y_coord"])) # Changed to page_num
        return final_headings

    def step_5_enforce_hierarchy(self, headings):

        if not headings:
            return []

        corrected_headings = []

        last_level_num = 0

        for heading in headings:
            current_level_num = int(heading['level'][1:])

            if current_level_num > last_level_num + 1:

                new_level_num = last_level_num + 1
                corrected_heading = heading.copy()
                corrected_heading['level'] = f"H{new_level_num}"
                corrected_headings.append(corrected_heading)
                last_level_num = new_level_num
            else:

                corrected_headings.append(heading)
                last_level_num = current_level_num

        return corrected_headings

    def step_6_merge_consecutive_headings(self, headings):
        if not headings:
            return []

        merged_headings = [headings[0]]

        for current_heading in headings[1:]:
            last_heading = merged_headings[-1]

            vertical_threshold = last_heading['font_size'] * 2.0
            actual_vertical_distance = current_heading['y_coord'] - last_heading['y_coord']

            if (current_heading['level'] == last_heading['level'] and
                    current_heading['page_num'] == last_heading['page_num'] and # Changed to page_num
                    actual_vertical_distance < vertical_threshold):

                last_heading['text'] += ' ' + current_heading['text']
            else:

                merged_headings.append(current_heading)

        return merged_headings

    def extract(self):

        self._get_underline_bboxes()
        self.step_1_extract_features()
        self.step_2_analyze_styles()

        candidates = self.step_3_score_and_classify_headings(allow_body_size=False)

        if not candidates:
            print("No headings found. Retrying with body-sized text as potential headings...")
            candidates = self.step_3_score_and_classify_headings(allow_body_size=True)

        refined_headings = self.step_4_refine_with_word_count(candidates)
        hierarchical_headings = self.step_5_enforce_hierarchy(refined_headings)
        final_headings = self.step_6_merge_consecutive_headings(hierarchical_headings)

        outline = [
            {"level": h["level"], "text": h["text"], "page_num": h["page_num"]} # Changed to page_num
            for h in final_headings
        ]
        return outline


input_dir = 'input'
output_dir = 'output'

for pdf_name in os.listdir(input_dir):
    if pdf_name.lower().endswith(".pdf"):
        print(f"Processing {pdf_name}...")

        pdf_path = os.path.join(input_dir, pdf_name)
        pdf = pymupdf.open(pdf_path)

        title = pdf.metadata.get('title', "No title found")
        if not title:
            title = "No title found"

        output_data = {
            "title": title,
            "outline": []
        }
        method_title = ""

        if output_data['title'] == "No title found":
            if pdf.page_count > 0:
                page = pdf[0] # Renamed page_num to page for clarity

                top_zone = pymupdf.Rect(page.rect.x0, page.rect.y0, page.rect.x1, page.rect.height * 0.10)
                page_area = page.rect.width * page.rect.height

                has_large_image_at_top = any(
                    (pymupdf.Rect(img['bbox']).intersects(top_zone)) and
                    ((pymupdf.Rect(img['bbox']).width * pymupdf.Rect(img['bbox']).height / page_area) >= 0.50) and (
                                (pymupdf.Rect(img['bbox']).width * pymupdf.Rect(img['bbox']).height / page_area) < 0.97)
                    for img in page.get_image_info()
                )

                if not page.get_text().strip() or has_large_image_at_top:

                    print("Page is either empty or has a large image at the top.")

                    image_list = page.get_images(full=True)
                    if image_list:

                        image_list.sort(key=lambda img: img[0], reverse=True)
                        xref = image_list[0][0]
                        base_image = pdf.extract_image(xref)
                        image_bytes = base_image["image"]

                        try:
                            image = Image.open(io.BytesIO(image_bytes))
                            ocr_data = pytesseract.image_to_data(image, lang='eng+fra',
                                                                 output_type=pytesseract.Output.DATAFRAME)

                            ocr_data = ocr_data[ocr_data.conf > 0]
                            ocr_data['text'] = ocr_data['text'].astype(str).str.strip()
                            ocr_data = ocr_data[ocr_data.text != '']

                            if not ocr_data.empty:

                                blocks_grouped = ocr_data.groupby('block_num')

                                block_candidates = []
                                for block_num, block_df in blocks_grouped:
                                    lines_in_block = \
                                        block_df.sort_values(by=['par_num', 'line_num', 'word_num']).groupby(
                                            ['par_num', 'line_num'])['text'].apply(' '.join)
                                    full_text = '\n'.join(lines_in_block)

                                    avg_height = block_df['height'].mean()
                                    text_length = len(full_text)

                                    block_candidates.append({
                                        'text': full_text,
                                        'avg_height': avg_height,
                                        'length': text_length
                                    })

                                if block_candidates:

                                    max_height = max(
                                        b['avg_height'] for b in block_candidates) if block_candidates else 0
                                    max_length = max(b['length'] for b in block_candidates) if block_candidates else 0

                                    w_font = 0.7
                                    w_len = 0.3

                                    best_block = None
                                    max_score = -1
                                    for block in block_candidates:
                                        font_score = block['avg_height'] / max_height if max_height > 0 else 0
                                        len_score = block['length'] / max_length if max_length > 0 else 0

                                        total_score = (w_font * font_score) + (w_len * len_score)

                                        if total_score > max_score:
                                            max_score = total_score
                                            best_block = block

                                    if best_block:

                                        heuristic_title = " ".join(best_block['text'].split())
                                        print(f"Title determined by block score heuristic: '{heuristic_title}'")
                                        output_data['title'] = heuristic_title
                                    else:
                                        print("Could not determine a best block for the title.")
                                else:
                                    print("Could not reconstruct any blocks from OCR data.")
                            else:
                                print("OCR did not return any usable data.")

                        except Exception as e:
                            print(f"An error occurred during OCR: {e}")
                    else:
                        print("No images found on the first page to perform OCR.")
                else:

                    blocks = page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)["blocks"]

                    if not blocks:
                        print("No text found on the first page.")

                    max_font_size = 0
                    title_block = None

                    for block in blocks:
                        if "lines" in block:
                            for line in block["lines"]:
                                if "spans" in line:
                                    for span in line["spans"]:
                                        if span["size"] > max_font_size:
                                            max_font_size = span["size"]
                                            title_block = block

                    if title_block:
                        title_candidates = []

                        for line in title_block["lines"]:
                            if any(span["size"] == max_font_size for span in line["spans"]):
                                for span in line["spans"]:

                                    text_candidate = span["text"].strip()
                                    if text_candidate:
                                        title_candidates.append(text_candidate)

                        if title_candidates:
                            heuristic_title = " ".join(title_candidates)
                            print('Title is determined heuristically')
                            output_data['title'] = heuristic_title

                    else:

                        print("Could not determine title using font size")

        else:
            method_title = "metadata"

        toc = pdf.get_toc()
        if toc:

            outline_method = "toc"

            for entry in toc:
                level, title, page_num = entry # Changed 'page' to 'page_num' to match desired output
                outline_pdf = {
                    "level": f"H{level}",
                    "text": title,
                    "page_num": page_num, # Changed to page_num
                }

                output_data["outline"].append(outline_pdf)
        else:

            outline_method = 'heuristic'
            print("TOC not found. Using heuristic model to extract outline...")
            extractor = pdf_outline_extractor(pdf_doc=pdf)
            heuristic_outline = extractor.extract()
            output_data["outline"] = heuristic_outline

        json_filename = os.path.join(output_dir, os.path.splitext(pdf_name)[0] + '.json')
        with open(json_filename, 'w') as json_output:
            json.dump(output_data, json_output, indent=4)

        print("successfully creates output.json")
        
        # if method_title == "metadata":
        #     feedback_title = input(" Type satisfied/not satisfied for title ")
        #     if feedback_title == "satisfied":
        #         pass
        #     else:
        #         page = pdf[0]
        #
        #         top_zone = pymupdf.Rect(page.rect.x0, page.rect.y0, page.rect.x1, page.rect.height * 0.10)
        #         page_area = page.rect.width * page.rect.height
        #
        #         has_large_image_at_top = any(
        #             (pymupdf.Rect(img['bbox']).intersects(top_zone)) and
        #             ((pymupdf.Rect(img['bbox']).width * pymupdf.Rect(img['bbox']).height / page_area) >= 0.50) and (
        #                     (pymupdf.Rect(img['bbox']).width * pymupdf.Rect(img['bbox']).height / page_area) < 0.97)
        #             for img in page.get_image_info()
        #         )
        #
        #         if not page.get_text().strip() or has_large_image_at_top:
        #
        #             print("Page is either empty or has a large image at the top.")
        #
        #             image_list = page.get_images(full=True)
        #             if image_list:
        #
        #                 image_list.sort(key=lambda img: img[0], reverse=True)
        #                 xref = image_list[0][0]
        #                 base_image = pdf.extract_image(xref)
        #                 image_bytes = base_image["image"]
        #
        #                 try:
        #                     image = Image.open(io.BytesIO(image_bytes))
        #                     ocr_data = pytesseract.image_to_data(image, lang='eng+fra',
        #                                                          output_type=pytesseract.Output.DATAFRAME)
        #
        #                     ocr_data = ocr_data[ocr_data.conf > 0]
        #                     ocr_data['text'] = ocr_data['text'].astype(str).str.strip()
        #                     ocr_data = ocr_data[ocr_data.text != '']
        #
        #                     if not ocr_data.empty:
        #
        #                         blocks_grouped = ocr_data.groupby('block_num')
        #
        #                         block_candidates = []
        #                         for block_num, block_df in blocks_grouped:
        #                             lines_in_block = \
        #                                 block_df.sort_values(by=['par_num', 'line_num', 'word_num']).groupby(
        #                                     ['par_num', 'line_num'])['text'].apply(' '.join)
        #                             full_text = '\n'.join(lines_in_block)
        #
        #                             avg_height = block_df['height'].mean()
        #                             text_length = len(full_text)
        #
        #                             block_candidates.append({
        #                                 'text': full_text,
        #                                 'avg_height': avg_height,
        #                                 'length': text_length
        #                             })
        #
        #                         if block_candidates:
        #
        #                             max_height = max(
        #                                 b['avg_height'] for b in block_candidates) if block_candidates else 0
        #                             max_length = max(b['length'] for b in block_candidates) if block_candidates else 0
        #
        #                             w_font = 0.7
        #                             w_len = 0.3
        #
        #                             best_block = None
        #                             max_score = -1
        #                             for block in block_candidates:
        #                                 font_score = block['avg_height'] / max_height if max_height > 0 else 0
        #                                 len_score = block['length'] / max_length if max_length > 0 else 0
        #
        #                                 total_score = (w_font * font_score) + (w_len * len_score)
        #
        #                                 if total_score > max_score:
        #                                     max_score = total_score
        #                                     best_block = block
        #
        #                             if best_block:
        #
        #                                 heuristic_title = " ".join(best_block['text'].split())
        #                                 print(f"Title determined by block score heuristic: '{heuristic_title}'")
        #                                 output_data['title'] = heuristic_title
        #                             else:
        #                                 print("Could not determine a best block for the title.")
        #                         else:
        #                             print("Could not reconstruct any blocks from OCR data.")
        #                     else:
        #                         print("OCR did not return any usable data.")
        #
        #                 except Exception as e:
        #                     print(f"An error occurred during OCR: {e}")
        #             else:
        #                 print("No images found on the first page to perform OCR.")
        #         else:
        #
        #             blocks = page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)["blocks"]
        #
        #             if not blocks:
        #                 print("No text found on the first page.")
        #
        #             max_font_size = 0
        #             title_block = None
        #
        #             for block in blocks:
        #                 if "lines" in block:
        #                     for line in block["lines"]:
        #                         if "spans" in line:
        #                             for span in line["spans"]:
        #                                 if span["size"] > max_font_size:
        #                                     max_font_size = span["size"]
        #                                     title_block = block
        #
        #             if title_block:
        #                 title_candidates = []
        #
        #                 for line in title_block["lines"]:
        #                     if any(span["size"] == max_font_size for span in line["spans"]):
        #                         for span in line["spans"]:
        #
        #                             text_candidate = span["text"].strip()
        #                             if text_candidate:
        #                                 title_candidates.append(text_candidate)
        #
        #                 if title_candidates:
        #                     heuristic_title = " ".join(title_candidates)
        #                     print('Title is determined heuristically')
        #                     output_data['title'] = heuristic_title
        #
        #             else:
        #
        #                 print("Could not determine title using font size")
        #
        #     json_filename = os.path.join(output_dir, os.path.splitext(pdf_name)[0] + '.json')
        #
        #     with open(json_filename, 'w') as json_output:
        #         json.dump(output_data, json_output, indent=4)
        #
        #     print("successfully creates ouput.json")

        # if outline_method == "toc":
        #     feedback_outline = input(" type satisfied/ not satified with outline ")
        #     if feedback_outline == "satisfied":
        #         print("thank you for using our tool")
        #     else:
        #
        #         extractor = pdf_outline_extractor(pdf_doc=pdf)
        #         heuristic_outline = extractor.extract()
        #         output_data["outline"] = heuristic_outline
        #
        #         json_filename = os.path.join(output_dir, os.path.splitext(pdf_name)[0] + '.json')
        #
        #         with open(json_filename, 'w') as json_output:
        #             json.dump(output_data, json_output, indent=4)
        #
        #     print("successfully creates output.json")
        #     print("thank you for using our tool")
        #
        # page = pdf[0]
        # top_zone = pymupdf.Rect(page.rect.x0, page.rect.y0, page.rect.x1, page.rect.height * 0.10)
        # page_area = page.rect.width * page.rect.height
        #
        # has_large_image_at_top = any(
        #     (pymupdf.Rect(img['bbox']).intersects(top_zone)) and
        #     ((pymupdf.Rect(img['bbox']).width * pymupdf.Rect(img['bbox']).height / page_area) >= 0.50) and (
        #             (pymupdf.Rect(img['bbox']).width * pymupdf.Rect(img['bbox']).height / page_area) < 0.97)
        #     for img in page.get_image_info()
        # )
        #
        # if pdf.page_count == 1 and has_large_image_at_top:
        #     output_data["outline"] = []
        #     json_filename = os.path.join(output_dir, os.path.splitext(pdf_name)[0] + '.json')
        #
        #     with open(json_filename, 'w') as json_output:
        #         json.dump(output_data, json_output, indent=4)

        pdf.close()
