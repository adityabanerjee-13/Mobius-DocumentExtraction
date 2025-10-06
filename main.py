from fastapi import FastAPI
from fastapi.responses import JSONResponse
from typing import Annotated, Optional
from pydantic import BaseModel, Field
import tempfile
import shutil
from marker.converters.pdf import PdfConverter
from marker.models import create_model_dict
import json
import requests
import os

app = FastAPI(title="PDF Parser API", description="Parse PDFs using Marker", version="1.0")


class PDFParserConfig(BaseModel):
    file_url: Annotated[str, Field(description="CDN URL of the PDF file to process", examples=["https://example.com/document.pdf"])]
    optional_config: Annotated[
        Optional[dict], 
        Field(
            default={}, 
            description="Optional configuration parameters for PDF processing",
            examples=[{
                'ollama_model': "llama3.2:latest",
                "use_llm": True,
                "ollama_base_url": "http://ollama-keda.mobiusdtaas.ai",
                'llm_service': 'ollama',
                "page_range": [4],
                'disable_ocr': True,
                'output_json': True,
                "ignore_TOC": True,
                'ignore_before_TOC': True,
                "renderer": "markdown+chunks+pageMarkdown"
            }]
        )
    ] = {}


@app.post("/parse-pdf/")
async def parse_pdf(request: PDFParserConfig):
    """
    Download a PDF file from CDN URL and parse it using Marker.
    Provide file URL and optional configuration.
    Returns structured text, markdown, and chunks.
    """
    tmp_path = None
    try:
        # Validate and get configuration
        parser_config = request
        optional_config = parser_config.optional_config
        
        ollama_base_url: str = optional_config.get('ollama_base_url', "http://ollama-keda.mobiusdtaas.ai")
        ollama_model: str = optional_config.get('ollama_model', "llama3.2:latest")
        use_llm: bool = optional_config.get('use_llm', False)
        llm_service: str = optional_config.get('llm_service', 'ollama')
        if llm_service.lower() == 'ollama':
            llm_service = 'marker.services.ollama.OllamaService'
        disable_ocr: bool = optional_config.get('disable_ocr', True)
        output_json: bool = optional_config.get('output_json', True)
        ignore_TOC: bool = optional_config.get('ignore_TOC', True)
        ignore_before_TOC: bool = optional_config.get('ignore_before_TOC', True)
        renderer: str = optional_config.get('renderer', "pageMarkdown+chunks")
        output_path: str = optional_config.get('output_path', "./")

        # Download file from CDN URL
        if not parser_config.file_url:
            return JSONResponse(content={"error": "file_url is required"}, status_code=400)
        
        try:
            response = requests.get(parser_config.file_url, stream=True, timeout=30)
            response.raise_for_status()
            
            # Check if it's a PDF file
            content_type = response.headers.get('content-type', '')
            if 'application/pdf' not in content_type and not parser_config.file_url.lower().endswith('.pdf'):
                return JSONResponse(
                    content={"error": "URL does not point to a PDF file"}, 
                    status_code=400
                )
            
        except requests.exceptions.RequestException as e:
            return JSONResponse(
                content={"error": f"Failed to download file from URL: {str(e)}"}, 
                status_code=400
            )

        # Save downloaded file temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    tmp.write(chunk)
            tmp_path = tmp.name

        # Initialize converter with the provided/default configuration
        converter = PdfConverter(
            artifact_dict=create_model_dict(),
            config={
                "use_llm": use_llm,
                "ollama_base_url": ollama_base_url,
                "ollama_model": ollama_model,
                "disable_ocr": disable_ocr,
                "output_json": output_json,
                "ignore_TOC": ignore_TOC,
                "ignore_before_TOC": ignore_before_TOC,
                "renderer": renderer,
            }
        )
        
        # Run the converter
        output = converter(tmp_path)

        return JSONResponse(content=output, status_code=200)

    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)

    finally:
        # Clean up temporary file
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass  # Ignore cleanup errors
