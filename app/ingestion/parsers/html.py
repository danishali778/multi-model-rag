from __future__ import annotations

from bs4 import BeautifulSoup, NavigableString, Tag

from app.domain.entities.rag import ExtractedDocument
from app.ingestion.parsers.base import BaseParser


class HtmlParser(BaseParser):
    source_type = "html"

    def parse(self, raw_bytes: bytes, metadata: dict) -> ExtractedDocument:
        html = raw_bytes.decode("utf-8", errors="ignore")
        soup = BeautifulSoup(html, "html.parser")
        title = soup.title.string.strip() if soup.title and soup.title.string else self.default_title(metadata)
        root = soup.body or soup
        blocks = []
        section_path: list[str] = []
        heading_ids: list = []
        order_index = 0

        def current_parent_id():
            return heading_ids[-1] if heading_ids else None

        def push_block(block_type: str, text: str, *, heading_level: int | None = None, metadata_block: dict | None = None):
            nonlocal order_index
            normalized = " ".join(text.split()) if block_type not in {"code", "table"} else text.strip()
            if not normalized:
                return None
            block = self.make_block(
                block_type=block_type,
                text=normalized,
                order_index=order_index,
                section_path=section_path,
                heading_level=heading_level,
                parent_block_id=current_parent_id(),
                metadata=metadata_block,
            )
            blocks.append(block)
            order_index += 1
            return block

        def walk(node: Tag):
            for child in node.children:
                if isinstance(child, NavigableString):
                    continue
                if not isinstance(child, Tag):
                    continue
                name = child.name.lower()
                if name in {"script", "style", "noscript", "nav", "footer", "aside"}:
                    continue
                if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
                    level = int(name[1])
                    heading_text = child.get_text(" ", strip=True)
                    section_path[:] = section_path[: level - 1] + [heading_text]
                    heading_ids[:] = heading_ids[: level - 1]
                    block = push_block("heading", heading_text, heading_level=level)
                    if block is not None:
                        heading_ids.append(block.id)
                    continue
                if name == "p":
                    push_block("paragraph", child.get_text(" ", strip=True))
                    continue
                if name in {"ul", "ol"}:
                    for index, item in enumerate(child.find_all("li", recursive=False), start=1):
                        push_block("list_item", item.get_text(" ", strip=True), metadata_block={"list_depth": 0, "list_index": index})
                    continue
                if name == "table":
                    rows = []
                    for row in child.find_all("tr"):
                        cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"])]
                        if any(cells):
                            rows.append(" | ".join(cells))
                    push_block("table", "\n".join(rows), metadata_block={"row_count": len(rows)})
                    continue
                if name in {"pre", "code"}:
                    push_block("code", child.get_text("\n", strip=True))
                    continue
                if name in {"article", "section", "main", "div", "body"}:
                    walk(child)
                    continue
                text = child.get_text(" ", strip=True)
                if text and name not in {"span", "strong", "em", "a"}:
                    push_block("paragraph", text)

        walk(root)
        return self.build_document(title=title, metadata=metadata, blocks=blocks)
