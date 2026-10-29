#!/usr/bin/env python3
"""Defer selected static HTML images until they approach the viewport."""

import argparse
from html.parser import HTMLParser
from pathlib import Path


def attributes(raw_tag):
    """Return attribute name and value spans without reformatting the tag."""
    result = {}
    pos = 4  # immediately after <img
    while pos < len(raw_tag):
        while pos < len(raw_tag) and raw_tag[pos].isspace():
            pos += 1
        if pos >= len(raw_tag) or raw_tag[pos] in "/>":
            break
        start = pos
        while pos < len(raw_tag) and raw_tag[pos] not in " \t\r\n=/>":
            pos += 1
        end = pos
        name = raw_tag[start:end].lower()
        while pos < len(raw_tag) and raw_tag[pos].isspace():
            pos += 1
        if pos >= len(raw_tag) or raw_tag[pos] != "=":
            result[name] = (start, end, None, None, None)
            continue
        pos += 1
        while pos < len(raw_tag) and raw_tag[pos].isspace():
            pos += 1
        quote = raw_tag[pos] if pos < len(raw_tag) and raw_tag[pos] in "\"'" else None
        if quote:
            pos += 1
            value_start = pos
            while pos < len(raw_tag) and raw_tag[pos] != quote:
                pos += 1
            value_end = pos
            pos += 1
        else:
            value_start = pos
            while pos < len(raw_tag) and raw_tag[pos] not in " \t\r\n>":
                pos += 1
            value_end = pos
        result[name] = (start, end, value_start, value_end, quote)
    return result


class ImageFinder(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=False)
        self.html = html
        self.line_starts = [0]
        for line in html.splitlines(keepends=True):
            self.line_starts.append(self.line_starts[-1] + len(line))
        self.images = []
        self.last_external_script_end = None
        self.script_external = False
        self.body_end = None

    def source_offset(self):
        line, column = self.getpos()
        return self.line_starts[line - 1] + column

    def handle_starttag(self, tag, attrs):
        if tag == "img":
            start = self.source_offset()
            raw = self.get_starttag_text()
            self.images.append((start, start + len(raw), raw, dict(attrs).get("src")))
        elif tag == "script":
            self.script_external = dict(attrs).get("src") is not None

    handle_startendtag = handle_starttag

    def handle_endtag(self, tag):
        if tag == "script" and self.script_external:
            start = self.source_offset()
            self.last_external_script_end = self.html.find(">", start) + 1
            self.script_external = False
        elif tag == "body":
            self.body_end = self.source_offset()


def defer_tag(raw):
    attrs = attributes(raw)
    if "src" not in attrs or attrs["src"][2] is None:
        raise ValueError("selected image has no src attribute")
    edits = []
    for name in ("src", "srcset"):
        if name in attrs:
            start, end, _, _, _ = attrs[name]
            edits.append((start, end, "data-deferred-" + name))
    if "class" in attrs and attrs["class"][2] is not None:
        _, _, start, end, quote = attrs["class"]
        value = raw[start:end]
        replacement = value + " deferred-image"
        if quote is None:
            replacement = '"' + replacement + '"'
        edits.append((start, end, replacement))
    else:
        insert = raw.rfind("/>")
        if insert < 0:
            insert = raw.rfind(">")
        edits.append((insert, insert, ' class="deferred-image"'))
    for start, end, replacement in sorted(edits, reverse=True):
        raw = raw[:start] + replacement + raw[end:]
    return raw


def loader_script(margin):
    return f'''<script>
  (function () {{
    var images = document.querySelectorAll("img.deferred-image");
    function loadImage(image) {{
      if (image.dataset.deferredSrcset) {{
        image.srcset = image.dataset.deferredSrcset;
      }}
      image.src = image.dataset.deferredSrc;
    }}
    if (!("IntersectionObserver" in window)) {{
      images.forEach(loadImage);
      return;
    }}
    var observer = new IntersectionObserver(function (entries) {{
      entries.forEach(function (entry) {{
        if (entry.isIntersecting) {{
          loadImage(entry.target);
          observer.unobserve(entry.target);
        }}
      }});
    }}, {{ rootMargin: "0px 0px {margin}px 0px" }});
    images.forEach(function (image) {{ observer.observe(image); }});
  }}());
</script>'''


def transform(html, image_sources, margin):
    parser = ImageFinder(html)
    parser.feed(html)
    counts = {source: 0 for source in image_sources}
    edits = []
    for start, end, raw, source in parser.images:
        if source in counts:
            counts[source] += 1
            edits.append((start, end, defer_tag(raw)))
    missing = [source for source, count in counts.items() if count == 0]
    if missing:
        raise ValueError("image src not found: " + ", ".join(missing))
    if parser.last_external_script_end is not None:
        insert = parser.last_external_script_end
        script = "\n" + loader_script(margin)
    elif parser.body_end is not None:
        insert = parser.body_end
        script = loader_script(margin) + "\n"
    else:
        insert = len(html)
        script = "\n" + loader_script(margin)
    edits.append((insert, insert, script))
    for start, end, replacement in sorted(edits, reverse=True):
        html = html[:start] + replacement + html[end:]
    if not html.endswith("\n"):
        html += "\n"
    return html, counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="source HTML file")
    parser.add_argument("output", type=Path, help="new HTML file")
    parser.add_argument("--image", action="append", required=True,
                        help="exact src value of an image to defer; repeat as needed")
    parser.add_argument("--margin-px", type=int, default=100,
                        help="load this many pixels before an image enters view")
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        parser.error("input and output must be different files")
    if args.margin_px < 0:
        parser.error("--margin-px must be nonnegative")
    try:
        result, counts = transform(args.input.read_text(encoding="utf-8"),
                                   args.image, args.margin_px)
    except (OSError, UnicodeError, ValueError) as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(result, encoding="utf-8")
    print(f"Wrote {args.output}; deferred " +
          ", ".join(f"{source} ({count})" for source, count in counts.items()))


if __name__ == "__main__":
    main()
