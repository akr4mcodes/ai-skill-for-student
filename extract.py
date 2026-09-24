#!/usr/bin/env python3
import os
import sys
import json
import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any

import pymupdf
import pymupdf4llm

VERSION = "1.0.0"
FALLBACK_THRESHOLD = 5000
MIN_IMAGE_SIZE = 10


class ExtractionError(Exception):
    def __init__(self, message: str, stage: str = None, original_error: Exception = None):
        self.message = message
        self.stage = stage
        self.original_error = original_error
        super().__init__(self.message)

    def __str__(self):
        if self.stage:
            return f"[{self.stage}] {self.message}"
        return self.message


class PDFExtractor:
    def __init__(self, pdf_path: str):
        self.pdf_path = Path(pdf_path).resolve()
        self.doc = None
        self.page_count = 0
        self._validate_pdf()
        self._open_pdf()

    def _validate_pdf(self) -> None:
        if not self.pdf_path.exists():
            raise ExtractionError(f"File not found: {self.pdf_path}", stage="validation")
        if not self.pdf_path.is_file():
            raise ExtractionError(f"Not a file: {self.pdf_path}", stage="validation")
        try:
            with open(self.pdf_path, 'rb') as f:
                header = f.read(5)
                if header != b'%PDF-':
                    raise ExtractionError(
                        f"Invalid PDF header (expected %PDF-, got {header!r})",
                        stage="validation"
                    )
        except PermissionError as e:
            raise ExtractionError(f"Permission denied: {self.pdf_path}", stage="validation", original_error=e)
        except IOError as e:
            raise ExtractionError(f"Cannot read file: {e}", stage="validation", original_error=e)

    def _open_pdf(self) -> None:
        try:
            self.doc = pymupdf.open(self.pdf_path)
            self.page_count = len(self.doc)
        except Exception as e:
            raise ExtractionError(f"Cannot open PDF: {e}", stage="open", original_error=e)

    def close(self) -> None:
        if self.doc:
            self.doc.close()
            self.doc = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def get_file_metadata(self) -> Dict[str, Any]:
        size_bytes = self.pdf_path.stat().st_size
        size_human = size_bytes
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_human < 1024:
                size_human = f"{size_human:.1f} {unit}"
                break
            size_human /= 1024
        else:
            size_human = f"{size_human:.1f} TB"

        return {
            "path": str(self.pdf_path),
            "filename": self.pdf_path.name,
            "size_bytes": size_bytes,
            "size_human": size_human
        }

    def get_pdf_metadata(self) -> Dict[str, Any]:
        meta = self.doc.metadata

        def parse_pdf_date(date_str: str) -> str:
            if not date_str:
                return ""
            if date_str.startswith("D:"):
                date_str = date_str[2:]
            try:
                if len(date_str) >= 14:
                    dt = datetime.strptime(date_str[:14], "%Y%m%d%H%M%S")
                    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                elif len(date_str) >= 8:
                    dt = datetime.strptime(date_str[:8], "%Y%m%d")
                    return dt.strftime("%Y-%m-%d")
            except ValueError:
                pass
            return date_str

        format_str = meta.get("format", "")
        pdf_version = ""
        if format_str.startswith("PDF "):
            pdf_version = format_str[4:]

        return {
            "title": meta.get("title", ""),
            "author": meta.get("author", ""),
            "subject": meta.get("subject", ""),
            "keywords": meta.get("keywords", ""),
            "creator": meta.get("creator", ""),
            "producer": meta.get("producer", ""),
            "creation_date": parse_pdf_date(meta.get("creationDate", "")),
            "modification_date": parse_pdf_date(meta.get("modDate", "")),
            "pdf_version": pdf_version,
            "page_count": self.page_count,
            "encrypted": self.doc.is_encrypted
        }

    def get_page_info(self) -> List[Dict[str, Any]]:
        pages_info = []
        for i, page in enumerate(self.doc):
            rect = page.rect
            text = page.get_text()
            image_list = page.get_images(full=True)
            annot_count = 0
            for _ in page.annots():
                annot_count += 1

            pages_info.append({
                "number": i + 1,
                "width_pts": round(rect.width, 2),
                "height_pts": round(rect.height, 2),
                "width_mm": round(rect.width * 25.4 / 72, 1),
                "height_mm": round(rect.height * 25.4 / 72, 1),
                "rotation": page.rotation,
                "has_text": bool(text.strip()),
                "char_count": len(text),
                "has_images": len(image_list) > 0,
                "image_count": len(image_list),
                "annotation_count": annot_count
            })
        return pages_info

    def get_outline(self) -> List[Dict[str, Any]]:
        outline = []
        toc = self.doc.get_toc(simple=True)
        for item in toc:
            level, title, page = item
            outline.append({
                "level": level - 1,
                "title": title,
                "page": page if page > 0 else None
            })
        return outline

    def get_annotations(self) -> List[Dict[str, Any]]:
        annotations = []
        for page_num, page in enumerate(self.doc):
            for annot in page.annots():
                annot_info = {
                    "page": page_num + 1,
                    "type": annot.type[1] if annot.type else "Unknown",
                    "content": annot.info.get("content", ""),
                    "subject": annot.info.get("subject", ""),
                    "author": annot.info.get("title", ""),
                    "created": annot.info.get("creationDate", ""),
                    "modified": annot.info.get("modDate", ""),
                    "rect": list(annot.rect) if annot.rect else None
                }
                if annot.colors:
                    annot_info["color"] = annot.colors.get("stroke") or annot.colors.get("fill")
                annotations.append(annot_info)
        return annotations

    def get_links(self) -> List[Dict[str, Any]]:
        links = []
        for page_num, page in enumerate(self.doc):
            page_links = page.get_links()
            for link in page_links:
                link_info = {
                    "page": page_num + 1,
                    "rect": list(link.get("from", [])),
                }
                if "uri" in link:
                    link_info["type"] = "uri"
                    link_info["uri"] = link["uri"]
                elif "page" in link:
                    link_info["type"] = "goto"
                    link_info["target_page"] = link["page"] + 1
                else:
                    link_info["type"] = "other"

                if link_info["rect"]:
                    try:
                        rect = pymupdf.Rect(link_info["rect"])
                        link_info["text"] = page.get_text("text", clip=rect).strip()
                    except:
                        link_info["text"] = ""
                links.append(link_info)
        return links

    def get_fonts(self) -> List[Dict[str, Any]]:
        fonts_dict = {}
        for page_num, page in enumerate(self.doc):
            font_list = page.get_fonts(full=True)
            for font in font_list:
                xref, ext, font_type, basefont, name, encoding = font[:6]
                font_name = name or basefont or f"Unknown-{xref}"
                if font_name not in fonts_dict:
                    fonts_dict[font_name] = {
                        "name": font_name,
                        "type": font_type,
                        "encoding": encoding,
                        "pages_used": []
                    }
                if page_num + 1 not in fonts_dict[font_name]["pages_used"]:
                    fonts_dict[font_name]["pages_used"].append(page_num + 1)
        return list(fonts_dict.values())

    def extract_images(self, output_folder: str, min_size: int = None) -> List[Dict[str, Any]]:
        if min_size is None:
            min_size = MIN_IMAGE_SIZE

        output_path = Path(output_folder)
        output_path.mkdir(parents=True, exist_ok=True)
        extracted_images = []

        for page_num, page in enumerate(self.doc):
            image_list = page.get_images(full=True)
            for img_index, img in enumerate(image_list):
                xref = img[0]
                try:
                    base_image = self.doc.extract_image(xref)
                    if not base_image:
                        continue

                    image_bytes = base_image["image"]
                    image_ext = base_image.get("ext", "png")
                    width = base_image.get("width", 0)
                    height = base_image.get("height", 0)
                    colorspace = base_image.get("colorspace", 0)
                    bpc = base_image.get("bpc", 8)

                    if width < min_size and height < min_size:
                        continue

                    image_id = f"page{page_num + 1:03d}_img{img_index + 1:03d}"
                    filename = f"{image_id}.{image_ext}"
                    filepath = output_path / filename

                    with open(filepath, "wb") as f:
                        f.write(image_bytes)

                    position = None
                    try:
                        for img_rect in page.get_image_rects(xref):
                            position = list(img_rect)
                            break
                    except:
                        pass

                    cs_name = str(colorspace) if isinstance(colorspace, int) else colorspace

                    extracted_images.append({
                        "id": image_id,
                        "page": page_num + 1,
                        "filename": filename,
                        "filepath": str(filepath),
                        "width": width,
                        "height": height,
                        "colorspace": cs_name,
                        "bits_per_component": bpc,
                        "size_bytes": len(image_bytes),
                        "position": position
                    })

                except Exception as e:
                    print(f"Warning: Failed to extract image {xref} from page {page_num + 1}: {e}",
                          file=sys.stderr)
                    continue

        return extracted_images

    def extract_text_pymupdf4llm(self, pages: Tuple[int, int] = None) -> str:
        try:
            kwargs = {}
            if pages:
                kwargs['pages'] = list(range(pages[0] - 1, pages[1]))
            return pymupdf4llm.to_markdown(str(self.pdf_path), **kwargs)
        except Exception as e:
            raise ExtractionError(f"pymupdf4llm extraction failed: {e}", stage="extract", original_error=e)

    def extract_text_pymupdf(self, pages: Tuple[int, int] = None) -> str:
        if pages:
            start_page = pages[0] - 1
            end_page = pages[1]
        else:
            start_page = 0
            end_page = self.page_count

        text_parts = []
        for i in range(start_page, end_page):
            page = self.doc[i]
            page_text = page.get_text()
            text_parts.append(f"<!-- PAGE {i + 1} START -->")
            text_parts.append(page_text)
            text_parts.append(f"<!-- PAGE {i + 1} END -->")
            text_parts.append("")

        return "\n".join(text_parts)

    def extract_content(self, pages: Tuple[int, int] = None, method: str = "auto") -> Tuple[str, str]:
        if method == "pymupdf":
            return self.extract_text_pymupdf(pages), "pymupdf"
        elif method == "pymupdf4llm":
            return self.extract_text_pymupdf4llm(pages), "pymupdf4llm"
        else:
            try:
                text = self.extract_text_pymupdf4llm(pages)
                if len(text.strip()) >= FALLBACK_THRESHOLD:
                    return text, "pymupdf4llm"

                text_fallback = self.extract_text_pymupdf(pages)
                if len(text_fallback.strip()) > len(text.strip()):
                    return text_fallback, "pymupdf (fallback)"

                return text, "pymupdf4llm"

            except ExtractionError:
                try:
                    return self.extract_text_pymupdf(pages), "pymupdf (fallback)"
                except Exception as e:
                    raise ExtractionError(f"All extraction methods failed: {e}", stage="extract", original_error=e)


def insert_image_markers(content: str, images: List[Dict[str, Any]]) -> str:
    if not images:
        return content

    images_by_page = {}
    for img in images:
        page = img["page"]
        if page not in images_by_page:
            images_by_page[page] = []

        y_position = 0.5
        if img.get("position") and len(img["position"]) >= 4:
            y_position = img["position"][1] / 842.0
            y_position = min(1.0, max(0.0, y_position))

        images_by_page[page].append({**img, "y_position": y_position})

    for page in images_by_page:
        images_by_page[page].sort(key=lambda x: x["y_position"])

    lines = content.split('\n')
    result_lines = []
    current_page = 0
    page_content_lines = []
    in_page = False

    for line in lines:
        if line.startswith("<!-- PAGE ") and "START" in line:
            try:
                current_page = int(line.split()[2])
                in_page = True
                page_content_lines = []
                result_lines.append(line)
                continue
            except (ValueError, IndexError):
                pass

        elif line.startswith("<!-- PAGE ") and "END" in line:
            if current_page in images_by_page and page_content_lines:
                page_images = images_by_page[current_page]
                total_lines = len(page_content_lines)

                insertions = []
                for img in page_images:
                    line_idx = int(img["y_position"] * total_lines)
                    line_idx = min(line_idx, total_lines - 1)
                    position_hint = "top" if img["y_position"] < 0.33 else \
                                   "bottom" if img["y_position"] > 0.66 else "middle"
                    marker = f"<!-- IMAGE: {img['filename']} ({img['width']}x{img['height']}px, {position_hint} of page) -->"
                    insertions.append((line_idx, marker))

                insertions.sort(key=lambda x: x[0], reverse=True)

                for line_idx, marker in insertions:
                    insert_at = line_idx
                    for i in range(line_idx, min(line_idx + 3, total_lines)):
                        if page_content_lines[i].strip() == '':
                            insert_at = i + 1
                            break
                    page_content_lines.insert(insert_at, marker)
                    page_content_lines.insert(insert_at + 1, '')

            result_lines.extend(page_content_lines)
            result_lines.append(line)
            in_page = False
            page_content_lines = []
            continue

        if in_page:
            page_content_lines.append(line)
        else:
            result_lines.append(line)

    if page_content_lines:
        result_lines.extend(page_content_lines)

    return '\n'.join(result_lines)


def build_yaml_header(
    file_meta: Dict[str, Any],
    pdf_meta: Dict[str, Any],
    extraction_info: Dict[str, Any],
    structure_info: Dict[str, Any]
) -> str:
    lines = ["---"]

    lines.append("# Extraction Information")
    lines.append(f"source_file: \"{file_meta['filename']}\"")
    lines.append(f"source_path: \"{file_meta['path']}\"")
    lines.append(f"extraction_date: \"{extraction_info['date']}\"")
    lines.append(f"extraction_method: \"{extraction_info['method']}\"")
    if extraction_info.get('pages'):
        lines.append(f"extracted_pages: \"{extraction_info['pages'][0]}-{extraction_info['pages'][1]}\"")
    else:
        lines.append(f"extracted_pages: \"1-{pdf_meta['page_count']}\"")
    lines.append(f"script_version: \"{VERSION}\"")
    lines.append("")

    lines.append("# File Information")
    lines.append(f"file_size_bytes: {file_meta['size_bytes']}")
    lines.append(f"file_size_human: \"{file_meta['size_human']}\"")
    lines.append(f"total_pages: {pdf_meta['page_count']}")
    if pdf_meta.get('pdf_version'):
        lines.append(f"pdf_version: \"{pdf_meta['pdf_version']}\"")
    lines.append("")

    lines.append("# PDF Metadata")
    if pdf_meta.get('title'):
        lines.append(f"pdf_title: \"{pdf_meta['title']}\"")
    if pdf_meta.get('author'):
        lines.append(f"pdf_author: \"{pdf_meta['author']}\"")
    if pdf_meta.get('subject'):
        lines.append(f"pdf_subject: \"{pdf_meta['subject']}\"")
    if pdf_meta.get('creator'):
        lines.append(f"pdf_creator: \"{pdf_meta['creator']}\"")
    if pdf_meta.get('producer'):
        lines.append(f"pdf_producer: \"{pdf_meta['producer']}\"")
    if pdf_meta.get('creation_date'):
        lines.append(f"pdf_creation_date: \"{pdf_meta['creation_date']}\"")
    if pdf_meta.get('modification_date'):
        lines.append(f"pdf_modification_date: \"{pdf_meta['modification_date']}\"")
    lines.append("")

    lines.append("# Document Structure")
    lines.append(f"has_outline: {str(structure_info.get('has_outline', False)).lower()}")
    lines.append(f"outline_items: {structure_info.get('outline_count', 0)}")
    lines.append(f"has_annotations: {str(structure_info.get('has_annotations', False)).lower()}")
    lines.append(f"annotation_count: {structure_info.get('annotation_count', 0)}")
    lines.append(f"has_links: {str(structure_info.get('has_links', False)).lower()}")
    lines.append(f"link_count: {structure_info.get('link_count', 0)}")
    lines.append(f"total_images: {structure_info.get('image_count', 0)}")
    if structure_info.get('image_count', 0) > 0:
        lines.append(f"image_folder: \"./images/\"")

    lines.append("---")
    return '\n'.join(lines)


def build_outline_section(outline: List[Dict[str, Any]]) -> str:
    if not outline:
        return ""

    lines = ["", "# Document Outline (Bookmarks)", ""]
    for item in outline:
        indent = "  " * item["level"]
        page_ref = f" [page {item['page']}]" if item['page'] else ""
        lines.append(f"{indent}- {item['title']}{page_ref}")

    lines.append("")
    return '\n'.join(lines)


def build_annotations_section(annotations: List[Dict[str, Any]]) -> str:
    if not annotations:
        return ""

    lines = ["", "# Annotations", ""]
    lines.append("| Page | Type | Content | Author |")
    lines.append("|------|------|---------|--------|")

    for annot in annotations:
        content = annot.get('content', '').replace('\n', ' ').strip()
        if len(content) > 50:
            content = content[:47] + "..."
        content = content.replace('|', '\\|')

        author = annot.get('author', '')
        lines.append(f"| {annot['page']} | {annot['type']} | {content} | {author} |")

    lines.append("")
    return '\n'.join(lines)


def build_links_section(links: List[Dict[str, Any]]) -> str:
    external_links = [l for l in links if l.get('type') == 'uri' and l.get('uri')]
    if not external_links:
        return ""

    lines = ["", "# Hyperlinks", ""]
    lines.append("| Page | Text | URL |")
    lines.append("|------|------|-----|")

    for link in external_links:
        text = link.get('text', '').replace('\n', ' ').strip()
        if len(text) > 40:
            text = text[:37] + "..."
        text = text.replace('|', '\\|')

        uri = link.get('uri', '')
        if len(uri) > 60:
            uri = uri[:57] + "..."

        lines.append(f"| {link['page']} | {text} | {uri} |")

    lines.append("")
    return '\n'.join(lines)


def build_full_markdown(
    content: str,
    file_meta: Dict[str, Any],
    pdf_meta: Dict[str, Any],
    extraction_info: Dict[str, Any],
    outline: List[Dict[str, Any]],
    annotations: List[Dict[str, Any]],
    links: List[Dict[str, Any]],
    images: List[Dict[str, Any]]
) -> str:
    structure_info = {
        "has_outline": len(outline) > 0,
        "outline_count": len(outline),
        "has_annotations": len(annotations) > 0,
        "annotation_count": len(annotations),
        "has_links": len([l for l in links if l.get('type') == 'uri']) > 0,
        "link_count": len([l for l in links if l.get('type') == 'uri']),
        "image_count": len(images)
    }

    parts = []
    parts.append(build_yaml_header(file_meta, pdf_meta, extraction_info, structure_info))

    outline_section = build_outline_section(outline)
    if outline_section:
        parts.append(outline_section)

    annotations_section = build_annotations_section(annotations)
    if annotations_section:
        parts.append(annotations_section)

    links_section = build_links_section(links)
    if links_section:
        parts.append(links_section)

    parts.append("")
    parts.append("---")
    parts.append("")
    parts.append("# Extracted Content")
    parts.append("")

    content_with_images = insert_image_markers(content, images)
    parts.append(content_with_images)

    return '\n'.join(parts)


def build_metadata_json(
    file_meta: Dict[str, Any],
    pdf_meta: Dict[str, Any],
    extraction_info: Dict[str, Any],
    pages_info: List[Dict[str, Any]],
    outline: List[Dict[str, Any]],
    annotations: List[Dict[str, Any]],
    links: List[Dict[str, Any]],
    fonts: List[Dict[str, Any]],
    images: List[Dict[str, Any]]
) -> Dict[str, Any]:
    return {
        "extraction": {
            "source_file": file_meta["filename"],
            "source_path": file_meta["path"],
            "output_folder": extraction_info.get("output_folder", ""),
            "extraction_date": extraction_info["date"],
            "extraction_method": extraction_info["method"],
            "extracted_pages": extraction_info.get("pages"),
            "script_version": VERSION,
            "pymupdf_version": pymupdf.version[0],
        },
        "file": {
            "size_bytes": file_meta["size_bytes"],
            "size_human": file_meta["size_human"],
            "page_count": pdf_meta["page_count"],
            "pdf_version": pdf_meta.get("pdf_version", "")
        },
        "pdf_metadata": {
            "title": pdf_meta.get("title", ""),
            "author": pdf_meta.get("author", ""),
            "subject": pdf_meta.get("subject", ""),
            "keywords": pdf_meta.get("keywords", ""),
            "creator": pdf_meta.get("creator", ""),
            "producer": pdf_meta.get("producer", ""),
            "creation_date": pdf_meta.get("creation_date", ""),
            "modification_date": pdf_meta.get("modification_date", ""),
            "encrypted": pdf_meta.get("encrypted", False)
        },
        "structure": {
            "has_outline": len(outline) > 0,
            "outline_items": len(outline),
            "has_annotations": len(annotations) > 0,
            "annotation_count": len(annotations),
            "has_links": len(links) > 0,
            "link_count": len(links),
            "has_images": len(images) > 0,
            "image_count": len(images),
            "font_count": len(fonts)
        },
        "pages": pages_info,
        "outline": outline,
        "annotations": annotations,
        "links": links,
        "fonts": fonts,
        "images": images
    }


def main():
    parser = argparse.ArgumentParser(
        description="Extract PDF content to markdown with maximum fidelity."
    )
    parser.add_argument("input_pdf", help="Path to the PDF file to extract")
    parser.add_argument("output_folder", nargs="?", default=None,
                         help="Output folder (default: {input_name}_extracted/)")
    parser.add_argument("--pages", type=str, default=None, metavar="START-END",
                         help="Page range to extract, e.g., '1-10' (default: all pages)")
    parser.add_argument("--method", choices=["auto", "pymupdf4llm", "pymupdf"], default="auto",
                         help="Extraction method (default: auto)")
    parser.add_argument("--min-image-size", type=int, default=10, metavar="PIXELS",
                         help="Minimum image dimension to extract (default: 10)")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")

    args = parser.parse_args()

    pages = None
    if args.pages:
        try:
            parts = args.pages.split("-")
            if len(parts) == 2:
                pages = (int(parts[0]), int(parts[1]))
            else:
                print(f"Error: Invalid page range format: {args.pages}", file=sys.stderr)
                print("Use format: START-END (e.g., 1-10)", file=sys.stderr)
                sys.exit(1)
        except ValueError:
            print(f"Error: Invalid page range: {args.pages}", file=sys.stderr)
            sys.exit(1)

    input_path = Path(args.input_pdf)
    if args.output_folder:
        output_folder = Path(args.output_folder)
    else:
        output_folder = input_path.parent / f"{input_path.stem}_extracted"

    output_folder.mkdir(parents=True, exist_ok=True)
    images_folder = output_folder / "images"

    print(f"PDF Extractor v{VERSION}")
    print(f"Input: {input_path}")
    print(f"Output: {output_folder}")
    print()

    try:
        with PDFExtractor(str(input_path)) as pdf:
            print(f"Opened PDF: {pdf.page_count} pages")

            print("Extracting metadata...")
            file_meta = pdf.get_file_metadata()
            pdf_meta = pdf.get_pdf_metadata()
            pages_info = pdf.get_page_info()
            outline = pdf.get_outline()
            annotations = pdf.get_annotations()
            links = pdf.get_links()
            fonts = pdf.get_fonts()

            print(f"  - Outline items: {len(outline)}")
            print(f"  - Annotations: {len(annotations)}")
            print(f"  - Links: {len(links)}")
            print(f"  - Fonts: {len(fonts)}")

            print(f"Extracting images (min size: {args.min_image_size}px)...")
            images = pdf.extract_images(str(images_folder), min_size=args.min_image_size)
            print(f"  - Images extracted: {len(images)}")

            if not images:
                try:
                    images_folder.rmdir()
                except:
                    pass

            print(f"Extracting content (method: {args.method})...")
            content, method_used = pdf.extract_content(pages=pages, method=args.method)
            print(f"  - Method used: {method_used}")
            print(f"  - Content length: {len(content):,} characters")

        extraction_info = {
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "method": method_used,
            "pages": pages,
            "output_folder": str(output_folder)
        }

        print("Building output files...")
        markdown_content = build_full_markdown(
            content=content,
            file_meta=file_meta,
            pdf_meta=pdf_meta,
            extraction_info=extraction_info,
            outline=outline,
            annotations=annotations,
            links=links,
            images=images
        )

        md_path = output_folder / f"{input_path.stem}.md"
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(markdown_content)
        print(f"  - Saved: {md_path.name}")

        metadata = build_metadata_json(
            file_meta=file_meta,
            pdf_meta=pdf_meta,
            extraction_info=extraction_info,
            pages_info=pages_info,
            outline=outline,
            annotations=annotations,
            links=links,
            fonts=fonts,
            images=images
        )

        json_path = output_folder / "metadata.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        print(f"  - Saved: {json_path.name}")

        print()
        print("Extraction complete!")
        print(f"  Output folder: {output_folder}")
        print(f"  Markdown file: {md_path.name}")
        print(f"  Metadata file: {json_path.name}")
        if images:
            print(f"  Images folder: images/ ({len(images)} files)")

        sys.exit(0)

    except ExtractionError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()