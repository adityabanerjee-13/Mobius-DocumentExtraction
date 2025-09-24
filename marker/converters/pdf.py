import os

os.environ["TOKENIZERS_PARALLELISM"] = "false"  # disables a tokenizers warning

from collections import defaultdict
from typing import Annotated, Any, Dict, List, Optional, Type, Tuple, Union
import io
from contextlib import contextmanager
import tempfile

from marker.processors import BaseProcessor
from marker.services import BaseService
from marker.processors.llm.llm_table_merge import LLMTableMergeProcessor
from marker.providers.registry import provider_from_filepath
from marker.renderers.chunk import ChunkRenderer
from marker.builders.document import DocumentBuilder
from marker.builders.layout import LayoutBuilder
from marker.builders.line import LineBuilder
from marker.builders.ocr import OcrBuilder
from marker.builders.structure import StructureBuilder
from marker.converters import BaseConverter
from marker.processors.blockquote import BlockquoteProcessor
from marker.processors.code import CodeProcessor
from marker.processors.debug import DebugProcessor
from marker.processors.document_toc import DocumentTOCProcessor
from marker.processors.equation import EquationProcessor
from marker.processors.footnote import FootnoteProcessor
from marker.processors.ignoretext import IgnoreTextProcessor
from marker.processors.line_numbers import LineNumbersProcessor
from marker.processors.list import ListProcessor
from marker.processors.llm.llm_complex import LLMComplexRegionProcessor
from marker.processors.llm.llm_form import LLMFormProcessor
from marker.processors.llm.llm_image_description import LLMImageDescriptionProcessor
from marker.processors.llm.llm_table import LLMTableProcessor
from marker.processors.page_header import PageHeaderProcessor
from marker.processors.reference import ReferenceProcessor
from marker.processors.sectionheader import SectionHeaderProcessor
from marker.processors.table import TableProcessor
from marker.processors.text import TextProcessor
from marker.processors.block_relabel import BlockRelabelProcessor
from marker.processors.blank_page import BlankPageProcessor
from marker.processors.llm.llm_equation import LLMEquationProcessor
from marker.renderers.page_markdown import PageMarkdownRenderer
from marker.renderers.markdown import cleanup_text
from marker.renderers import BaseRenderer
from marker.schema.document import Document
from marker.schema import BlockTypes
from marker.schema.blocks import Block
from marker.schema.registry import register_block_class
from marker.util import strings_to_classes
from marker.processors.llm.llm_handwriting import LLMHandwritingProcessor
from marker.processors.order import OrderProcessor
from marker.services.gemini import GoogleGeminiService
from marker.processors.line_merge import LineMergeProcessor
from marker.processors.llm.llm_mathblock import LLMMathBlockProcessor
from marker.processors.llm.llm_page_correction import LLMPageCorrectionProcessor
from marker.processors.llm.llm_sectionheader import LLMSectionHeaderProcessor



def renderer2cls(name: str) -> Optional[str|List[str]]:
    if renderer == 'pageMarkdown':
        renderer = 'marker.renderers.page_markdown.PageMarkdownRenderer'
    elif renderer == 'markdown':
        renderer = 'marker.renderers.markdown.MarkdownRenderer'
    elif renderer == 'chunks':
        renderer = 'marker.renderers.chunk.ChunkRenderer'
    elif '+' in renderer:
        renderers = renderer.split('+')
        renderers = [r.strip() for r in renderers]
        renderers = [renderer2cls(r) for r in renderers]
    else:
        renderer = None



class PdfConverter(BaseConverter):
    """
    A converter for processing and rendering PDF files into Markdown, JSON, HTML and other formats.
    """

    override_map: Annotated[
        Dict[BlockTypes, Type[Block]],
        "A mapping to override the default block classes for specific block types.",
        "The keys are `BlockTypes` enum values, representing the types of blocks,",
        "and the values are corresponding `Block` class implementations to use",
        "instead of the defaults.",
    ] = defaultdict()
    use_llm: Annotated[
        bool,
        "Enable higher quality processing with LLMs.",
    ] = False
    default_processors: Tuple[BaseProcessor, ...] = (
        OrderProcessor,
        BlockRelabelProcessor,
        LineMergeProcessor,
        BlockquoteProcessor,
        CodeProcessor,
        DocumentTOCProcessor,
        EquationProcessor,
        FootnoteProcessor,
        IgnoreTextProcessor,
        LineNumbersProcessor,
        ListProcessor,
        PageHeaderProcessor,
        SectionHeaderProcessor,
        TableProcessor,
        LLMTableProcessor,
        LLMTableMergeProcessor,
        LLMFormProcessor,
        TextProcessor,
        LLMComplexRegionProcessor,
        LLMImageDescriptionProcessor,
        LLMEquationProcessor,
        LLMHandwritingProcessor,
        LLMMathBlockProcessor,
        LLMSectionHeaderProcessor,
        LLMPageCorrectionProcessor,
        ReferenceProcessor,
        BlankPageProcessor,
        DebugProcessor,
    )
    default_llm_service: BaseService = GoogleGeminiService

    def __init__(
        self,
        artifact_dict: Dict[str, Any],
        processor_list: Optional[List[str]] = None,
        config=None,
    ):
        
        renderer = config.get("renderer", None)
        renderer = renderer2cls(renderer)
        # remove renderer from config to avoid issues in other places
        if "renderer" in config:
            config.pop("renderer")
        
        llm_service = config.get("llm_service", None)
        # remove llm_service from config to avoid issues in other places
        if "llm_service" in config:
            config.pop("llm_service")

        super().__init__(config)

        if config is None:
            config = {}

        # Block types to ignore are initialized here.
        if config.get("ignore_TOC", False):
            self.ignore_blocks = ['TableOfContents']
        else:
            self.ignore_blocks = []

        for block_type, override_block_type in self.override_map.items():
            register_block_class(block_type, override_block_type)

        if processor_list is not None:
            processor_list = strings_to_classes(processor_list)
        else:
            processor_list = self.default_processors

        if renderer:
            renderer = strings_to_classes([renderer] if isinstance(renderer, str) else renderer)
        else:
            renderer = [PageMarkdownRenderer, ChunkRenderer]

        # Put here so that resolve_dependencies can access it
        self.artifact_dict = artifact_dict

        if llm_service:
            llm_service_cls = strings_to_classes([llm_service])[0]
            llm_service = self.resolve_dependencies(llm_service_cls)
        elif config.get("use_llm", False):
            llm_service = self.resolve_dependencies(self.default_llm_service)

        # Inject llm service into artifact_dict so it can be picked up by processors, etc.
        self.artifact_dict["llm_service"] = llm_service
        self.llm_service = llm_service

        self.renderer = renderer

        processor_list = self.initialize_processors(processor_list)
        self.processor_list = processor_list

        self.layout_builder_class = LayoutBuilder
        self.page_count = None  # Track how many pages were converted

    @contextmanager
    def filepath_to_str(self, file_input: Union[str, io.BytesIO]):
        temp_file = None
        try:
            if isinstance(file_input, str):
                yield file_input
            else:
                with tempfile.NamedTemporaryFile(
                    delete=False, suffix=".pdf"
                ) as temp_file:
                    if isinstance(file_input, io.BytesIO):
                        file_input.seek(0)
                        temp_file.write(file_input.getvalue())
                    else:
                        raise TypeError(
                            f"Expected str or BytesIO, got {type(file_input)}"
                        )

                yield temp_file.name
        finally:
            if temp_file is not None and os.path.exists(temp_file.name):
                os.unlink(temp_file.name)

    def build_document(self, filepath: str):
        provider_cls = provider_from_filepath(filepath)
        layout_builder = self.resolve_dependencies(self.layout_builder_class)
        line_builder = self.resolve_dependencies(LineBuilder)
        ocr_builder = self.resolve_dependencies(OcrBuilder)
        provider = provider_cls(filepath, self.config)
        document = DocumentBuilder(self.config, ignore_blocks=self.ignore_blocks)(
            provider, layout_builder, line_builder, ocr_builder
        )
        structure_builder_cls = self.resolve_dependencies(StructureBuilder)
        structure_builder_cls(document)

        for processor in self.processor_list:
            processor(document)

        return document

    def render(self, renderer_cls: Type[BaseRenderer], document: Document) -> Tuple[str, Any, Dict[str, Any]]:
        renderer = self.resolve_dependencies(renderer_cls)
        if renderer_cls.__name__ == "PageMarkdownRenderer":
            page_output, images, metadata = renderer(document)
            return "page_renders", page_output, images, metadata

        elif renderer_cls.__name__ == "ChunkRenderer":
            json_output, images, metadata = renderer(document)
            return "chunks", json_output, images, metadata

        elif renderer_cls.__name__ == "MarkdownRenderer":
            rendered, images, metadata = renderer(document)
            if isinstance(rendered, str):
                rendered = cleanup_text(rendered)
            return "markdown", rendered, images, metadata

    def render_document(self, document: Document) -> Dict[str, Any]:
        out_render = {}
        out_render['page_structure'] = {}
        for i, doc_child in enumerate(document.pages):
            if doc_child.ignore_for_output:
                out_render['page_structure'][doc_child.page_id] = []
            else:
                out_render['page_structure'][doc_child.page_id] = [str(identity) for identity in doc_child.structure]

        if isinstance(self.renderer, list):
            for j, renderer_cls in enumerate(self.renderer):
                key, rendered, images, metadata = self.render(renderer_cls, document)
                out_render[key] = rendered
                out_render['images'] = images
            out_render['metadata'] = metadata

        elif issubclass(self.renderer, BaseRenderer):
            key, rendered, images, metadata = self.render(self.renderer, document)
            out_render[key] = rendered
            out_render['metadata'] = metadata
            out_render['images'] = images

        else:
            raise ValueError("Renderer must be a BaseRenderer subclass or a list of BaseRenderer subclasses.")

        return out_render

    def __call__(self, filepath: str | io.BytesIO):
        with self.filepath_to_str(filepath) as temp_path:
            document = self.build_document(temp_path)
            self.page_count = len(document.pages)
            renderer = self.resolve_dependencies(self.renderer)
            rendered = renderer(document)
        return rendered
