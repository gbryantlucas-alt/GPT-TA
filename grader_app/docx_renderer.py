from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass

import mammoth
from bs4 import BeautifulSoup

from grader_app.models import Annotation

logger = logging.getLogger(__name__)


@dataclass
class RenderedEssay:
    html: str
    unresolved_flags: list[int]


class DocxHtmlRenderer:
    def __init__(self) -> None:
        self._cache: dict[str, RenderedEssay] = {}

    def render(self, path: str, annotations: list[Annotation]) -> RenderedEssay:
        key = f"{path}:{len(annotations)}"
        if key in self._cache:
            return self._cache[key]

        unresolved_flags: list[int] = []

        def image_converter(image):
            try:
                with image.open() as image_bytes:
                    encoded = image_bytes.read().hex()
                    binary = bytes.fromhex(encoded)
                    import base64

                    b64 = base64.b64encode(binary).decode("ascii")
                return {
                    "src": f"data:{image.content_type};base64,{b64}",
                    "class": "essay-image",
                }
            except Exception:
                logger.exception("Image extraction failed for %s", path)
                return {"alt": "[image could not be rendered]", "class": "image-error"}

        with open(path, "rb") as f:
            result = mammoth.convert_to_html(f, convert_image=mammoth.images.img_element(image_converter))
        base_html = result.value

        soup = BeautifulSoup(base_html, "html.parser")
        for i, img in enumerate(soup.find_all("img")):
            src = img.get("src", "")
            img["style"] = "max-width:95%;height:auto;border:1px solid #d9d9d9;border-radius:6px;cursor:pointer;"
            wrapper = soup.new_tag("a", href=f"img://{i}")
            img.wrap(wrapper)
            img["data-src"] = src

        body_html = str(soup)
        for idx, ann in enumerate(annotations):
            clean_excerpt = ann.excerpt.strip()
            if not clean_excerpt:
                unresolved_flags.append(idx)
                continue
            escaped = html.escape(clean_excerpt)
            mark = f'<a href="flag://{idx}"><mark class="human-flag" data-flag="{idx}">{escaped}</mark></a>'
            if escaped in body_html:
                body_html = body_html.replace(escaped, mark, 1)
                continue
            normalized_target = self._normalize(clean_excerpt)
            located = self._find_loose_segment(body_html, normalized_target)
            if located:
                seg, start, end = located
                body_html = body_html[:start] + body_html[start:end].replace(seg, mark, 1) + body_html[end:]
            else:
                unresolved_flags.append(idx)

        css = """
        body { font-family: 'Segoe UI', Arial, sans-serif; line-height: 1.55; padding: 18px; color:#1f2937; }
        h1,h2,h3 { color:#111827; margin-top: 18px; }
        p { margin: 0 0 10px 0; }
        .human-flag { background: #fff59d; padding: 1px 2px; border-radius:2px; }
        .image-error { background:#fff1f2; color:#b91c1c; padding:4px; border:1px solid #fecdd3; }
        """
        script = """
        <script>
        document.addEventListener('click', function(e){
          const a = e.target.closest('a');
          if(!a) return;
          if(a.href.startsWith('flag://') || a.href.startsWith('img://')) {
            e.preventDefault();
            window.location.href = a.href;
          }
        });
        </script>
        """
        full_html = f"<html><head><style>{css}</style></head><body>{body_html}{script}</body></html>"
        rendered = RenderedEssay(html=full_html, unresolved_flags=unresolved_flags)
        self._cache[key] = rendered
        return rendered

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"\W+", "", text.lower())

    def _find_loose_segment(self, body_html: str, target: str):
        if not target:
            return None
        chunks = re.finditer(r">([^<]{25,300})<", body_html)
        for m in chunks:
            seg = m.group(1)
            if target[:25] in self._normalize(seg):
                return seg, m.start(1), m.end(1)
        return None
