# 📄 Document Structure Extractor  
**Adobe Hackathon – Round 1A**  
**Theme:** Connecting the Dots Through Docs

---

## 🚀 Overview

This solution extracts a clean, hierarchical outline from any PDF (up to 50 pages), including:
- Title
- Headings (H1, H2, H3)
- Page numbers

It is designed to work offline, run entirely on CPU (amd64), and comply with strict execution and model size constraints.



## 🎯 Output Format

```json
{
  "title": "Understanding AI",
  "outline": [
    { "level": "H1", "text": "Introduction", "page": 1 },
    { "level": "H2", "text": "What is AI?", "page": 2 },
    { "level": "H3", "text": "History of AI", "page": 3 }
  ]
}
```

## 🚀 How to Build and Run

### 1. Prerequisites
- Docker must be installed and running.
- All input PDF files must be placed in an `input/` directory in the same folder as the Dockerfile.

### 2. Project Structure

```
Round1_A/
├── input/         # Folder for input data/files
├── libraries/     # Folder for project libraries/dependencies
├── output/        # Folder for output data/files
├── Dockerfile     # Dockerfile for containerization
├── main_1A.py     # Main Python script for Round 1A
├── README.md      # Project README file
└── requirements.txt # Python dependencies
```

### 3. Build the Docker Image
Navigate to the project's root directory in your terminal and run this command.
```bash
docker build --platform linux/amd64 -t solution:latest .
```

### 4. Run the Docker Image
This command runs the container, processing all PDFs from the input directory and saving the results to the output directory.
```bash
docker run --rm -v $(pwd)/input:/app/input -v $(pwd)/output:/app/output --network none solution:latest
```

📦 Follow this if running locally outside Docker:
Place PDFs in the input folder.
The output would be generated in output folder.


## 🧠 `approach_explanation.md` (300–500 words)

# Approach Explanation – Round 1A

The objective of Round 1A was to build an offline system that extracts structured outlines from PDFs including the title and headings (H1, H2, H3), supporting both textual and scanned documents, and working within strict CPU-only and size limits.

---

## Title Detection Strategy

We use a **3-level fallback system** to determine the document title:

1. **Metadata Check**:
   - If a valid title is available in the PDF metadata, it is used directly.
   - To ensure reliability, we enable a feedback option downstream to reject this title if it doesn’t match user expectations.

2. **Visual OCR**:
   - If metadata is missing or invalid, and if the document has large image on first page along with very minimal or no text, we use **Tesseract OCR** to extract text.
   - Among all recognized text blocks, the system picks the one with the **largest font size and character length** as the probable title.
   - Both the parameters are provided weights and the best text block extracted from image is provided as output.

3. **Fallback Text-Only Logic**:
   - For documents without metadata or failing to trigger OCR due to presence of substantial amount of text and absence of large image on first page, we analyze paragraph blocks from text.
   - The text block with the **largest font size** is picked as the title block. In case of ties, the first occurrence is selected.
   - Then for every line each span of text is compared with the largest font size. If any span matches the largest font then the entire line is selected as title from the selected title block.

---

## Outline Extraction (H1, H2, H3)

If a Table of Contents (TOC) is available, it is prioritized. Also if TOC is used to generate output then a feedback option is provided to user to reject that outline if it doesn’t match user expectations and our custom logic is implemented to provide output outline of pdf. Otherwise, only if TOC is not present then the logic proceeds with the following:

1. **Header/Footer Removal**:
   - Repeating text blocks on top/bottom of pages are identified and removed from heading candidates.

2. **Body Font Identification**:
   - The most frequently used font size is treated as the "body font."

3. **Heading Candidate Selection**:
   - Any block with font size larger than the body font is treated as a heading candidate.

4. **Scoring System**:
   Each candidate is scored based on the following:
   - Font size (compared to body font)
   - Boldness / Underline
   - Centered alignment
   - Font color
   - Length of heading (very large and very small text are penalised in the scoring system)

5.  Only candidates crossing a **minimum score threshold** are accepted. Headings are then grouped and labeled as H1, H2, or H3 based on  their font size and layout hierarchy. It is mandated that the first heading would always be H1 and hierarchy of headings is forced i.e. H3 cannot directly come after H1.

6.  After this the total words of headings must not exceed 10 percent of total words in document. If so then the heading with lower score are ignored and not recognized as headings in output outline of pdf.

7. If after this process the outline is still empty then and only then font size equal to detected body size is also considered for headings and the further process is repeated.

---

## Multilingual & OCR Support

Tesseract OCR is used to extract text from image-based PDFs. It has been tested to work with both **English and French**.
The rest of the entire code works for any language that pymupdf library can read and extract.
To incorporate more languages we just need to install more tessadata language files and update it in code easily.

---

## Performance & Compliance

- The model (Tesseract) is lightweight (<200MB).
- Execution is fast and fully CPU-based (≤10s for 50-page PDFs).
- No internet access or external APIs are used, making it compliant with the offline-first constraint.

---

## Integration with Round 1B

The output JSON files generated in the `output/` folder which needs to be copied and pasted inside the output_outline folder of our solution for Round 1B.

## Tech Stack
| Component                      | Technology                   |
| ---------------                | ---------------------------- |
| Language                       | Python 3                     |
| PDF Parsing                    | PyMuPDF (`fitz`) (library)   |
| OCR                            | Tesseract OCR (ml model)     |
| Text Processing                | Custom heuristics            |
| Output Format                  | JSON                         |
| python wrapper for tesseract   | Pytesseract (library)        |
| image manipulation before OCR  | Pillow (library)             |


NOTE: Important
The feedback portion of code is commented to ensure automated working during docker build and run.