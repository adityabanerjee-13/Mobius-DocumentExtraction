# Mobius-DocumentExtraction
This repository is used to extract documents(.pdf, .docx, .epub, Images, .ppt) to Markdown and chunks

## Inputs

- **output_json**: Whether to output the rendered document as JSON. By default, `False`.
- **page_range**: List of page numbers to process. By default, all pages are processed. eg. `[0,1,5,6,7,10,11,...]`
- **ignore_TOC**: Whether to ignore the page with Table of Contents page if detected. By default, `False`.
- **use_llm**: Whether to use LLM to enhance the parsing of the document. By default, `False`.
- **ollama_base_url**: Base URL for the Ollama LLM service. Default is `'http://localhost:11434'`.
- **llm_service**: The LLM service class to use. Default is `'marker.services.ollama.OllamaService'`.
- **disable_ocr**: Whether to disable OCR processing. By default, `True`, if the pdf/doc is not scanned, or in image formatable use OCR. OCR will make the process slow and detect empty spaces.
- **renderer**: The format of the output document can be one of the following (`markdown`|`json`|`pageMarkdown`|`chunks`|`pageMarkdown+chunks`'). Default is `json`.
    - for '`markdown`', the output dict with keys `markdown`, Dict[str, str].
    - for '`json`', the output dict with keys `json`, Dict[str, str].
    - for '`pageMarkdown`', the output dict with keys '`page_renders`' containing '`page numbers`' as keys and '`markdown`' or '`html`' as values, Dict[int, Dict[str, str]].
    - for '`chunks`', the output dict with keys '`chunks`'containing '`page_id`' as keys and '`html`' as values for the text, Dict[str, Dict[str, Any]].
    - for '`html`', the output is standard HTML format for PDFs, Dict[str, Any].
    - for '`pageMarkdown+chunks`', the output dict with keys '`page_renders`' and '`chunks`'.
    Output json format contains:
        - '`page_structure`': List[Dict[str, Any]]  (List of page-wise structure with text and blocks)
        - '`page_renders`'/'`chunks`' contain the information of the document.