#!/usr/bin/env python3
"""Defer below-the-fold <img> images using the data-src/data-srcset pattern.

Independently reproduces the image deferral implemented in
``webpage/optimized/deepseek/differdange-environment-local.html`` (the frozen
DeepSeek optimised page), given only:

  * the original HTML file (``webpage/differdange-environment-local.html``), and
  * the exact ``src`` values of the images to defer (the Waste and Projects
    quicklink card images).

What the tool does, byte-faithfully:

  1. For every ``<img ...>`` tag whose ``src="<value>"`` equals one of the
     supplied values, it renames ``src`` -> ``data-src`` and, when present,
     ``srcset`` -> ``data-srcset``. Nothing else in the file changes.
  2. It inserts a small deferral script immediately before ``</body>``. The
     script selects the deferred images (by default ``.pagequicklinks
     img[data-src]``, matching the quicklink cards; override with ``--selector``
     for other HTML structures, e.g. ``img[data-src]``), swaps the deferred
     attributes back onto ``src``/``srcset`` as each image enters the viewport
     via an IntersectionObserver with ``rootMargin: '0px'``, and falls back to
     loading everything immediately when IntersectionObserver is unavailable.
     With a non-default selector the script comment is made generic; the
     default selector keeps the script byte-for-byte identical to the one in
     the frozen page.

The original source file and the site assets are never modified; the result is
written to ``--output`` (or stdout). The implementation is standard-library
only (argparse + the ``bytes``/``str`` API).

This is written independently from the earlier ``tools/defer_images.py`` and
from ``webpage/optimized/differdange-environment-local.html``: the transform
here was derived from the observable deferral in the frozen DeepSeek page.
"""

import argparse
import sys

# Default src values used by the frozen page's quicklink cards (Waste, Projects).
# Passed on the command line; listed here for documentation only.
WASTE_SRC = "./differdange-environment-local_files/dechets.png"
PROJECTS_SRC = "./differdange-environment-local_files/netzerocities-528x388.jpg"

# Default image selector used by the injected deferral script. This matches the
# quicklink card structure of the frozen Differdange page; the script's selector
# string and comment are swapped when a custom --selector is supplied.
DEFAULT_SELECTOR = ".pagequicklinks img[data-src]"
_DEFAULT_COMMENT = (b"/* Defer the two below-the-fold quicklink card images (Waste, "
                    b"Projects) until they enter the viewport. */")
_GENERIC_COMMENT = b"/* Defer the below-the-fold images until they enter the viewport. */"

# Deferral script inserted before </body>. Byte-for-byte the script embedded in
# the frozen DeepSeek page: data-src/data-srcset + IntersectionObserver
# (rootMargin: '0px') + a no-observer fallback that loads immediately.
DEFER_SCRIPT = b"""<script>
/* Defer the two below-the-fold quicklink card images (Waste, Projects) until they enter the viewport. */
(function () {
    var imgs = document.querySelectorAll('.pagequicklinks img[data-src]');
    if (!imgs.length) return;
    function load(img) {
        var s = img.getAttribute('data-src');
        var ss = img.getAttribute('data-srcset');
        if (ss) img.setAttribute('srcset', ss);
        img.setAttribute('src', s);
        img.removeAttribute('data-src');
        img.removeAttribute('data-srcset');
    }
    /* Safe fallback: no IntersectionObserver -> load immediately so images always appear. */
    if (!('IntersectionObserver' in window)) {
        for (var i = 0; i < imgs.length; i++) load(imgs[i]);
        return;
    }
    var io = new IntersectionObserver(function (entries) {
        for (var i = 0; i < entries.length; i++) {
            if (entries[i].isIntersecting) {
                load(entries[i].target);
                io.unobserve(entries[i].target);
            }
        }
    }, { rootMargin: '0px' });
    for (var j = 0; j < imgs.length; j++) io.observe(imgs[j]);
})();
</script>"""


class MissingSourceError(Exception):
    """A supplied image ``src`` value was not found inside any <img> tag."""


def _find_img_tag_occurrences(data, value):
    """Locate every ``<img ... src="<value>" ...>`` tag in *data*.

    Returns a list of ``(tag_start, tag_end_exclusive, tag_bytes)`` tuples in
    document order. Only occurrences that sit inside a complete ``<img>`` tag
    (no ``>`` between the tag opener and the ``src`` attribute) are returned.
    """
    needle = b'src="' + value + b'"'
    occurrences = []
    pos = 0
    while True:
        i = data.find(needle, pos)
        if i == -1:
            break
        tag_start = data.rfind(b'<img', 0, i)
        tag_end = data.find(b'>', i)
        if tag_start != -1 and tag_end != -1 and b'>' not in data[tag_start:i]:
            occurrences.append((tag_start, tag_end + 1, data[tag_start:tag_end + 1]))
        pos = i + 1
    return occurrences


def defer_images(data, src_values):
    """Rewrite ``src`` -> ``data-src`` (and ``srcset`` -> ``data-srcset``) on the
    matching ``<img>`` tags.

    ``data`` is the original HTML as bytes; ``src_values`` is a sequence of the
    exact image ``src`` values to defer (each a ``bytes`` object). Returns
    ``(result_bytes, deferred_count)``. Raises :class:`MissingSourceError` if
    any supplied value has no ``<img>`` tag to defer. Every other byte of the
    document is preserved.
    """
    edits = []  # (tag_start, tag_end_exclusive, replacement_tag)
    for value in src_values:
        occurrences = _find_img_tag_occurrences(data, value)
        if not occurrences:
            needle = b'src="' + value + b'"'
            hint = ("value not found in the document"
                    if needle not in data
                    else "value appears only outside an <img> tag")
            raise MissingSourceError(
                "image src not found: %r (%s)" % (value.decode('utf-8', 'replace'), hint))
        for tag_start, tag_end, tag in occurrences:
            new_tag = tag.replace(b'src="' + value + b'"', b'data-src="' + value + b'"')
            if b'srcset="' in new_tag:
                new_tag = new_tag.replace(b'srcset="', b'data-srcset="')
            if new_tag != tag:
                edits.append((tag_start, tag_end, new_tag))

    out = data
    for tag_start, tag_end, new_tag in sorted(edits, reverse=True):
        out = out[:tag_start] + new_tag + out[tag_end:]
    return out, len(edits)


def insert_defer_script(data, script=DEFER_SCRIPT):
    """Insert *script* immediately before the closing ``</body>`` tag."""
    marker = b'</body>'
    idx = data.find(marker)
    if idx == -1:
        raise ValueError("no </body> tag found to anchor the deferral script")
    return data[:idx] + script + data[idx:]


def build_defer_script(selector=DEFAULT_SELECTOR):
    """Return the deferral script bytes that target *selector*.

    With the default selector the script is byte-for-byte the one embedded in
    the frozen DeepSeek page. With a custom selector the ``querySelectorAll``
    argument is replaced and the comment is made generic (the page-specific
    "Waste, Projects" note only applies to the Differdange quicklink cards), so
    the script is reusable on other HTML structures such as a plain
    ``img[data-src]``.
    """
    if selector == DEFAULT_SELECTOR:
        return DEFER_SCRIPT
    escaped = (selector.encode('utf-8')
               .replace(b'\\', b'\\\\')
               .replace(b"'", b"\\'"))
    script = DEFER_SCRIPT.replace(
        b"document.querySelectorAll('.pagequicklinks img[data-src]')",
        b"document.querySelectorAll('" + escaped + b"')")
    script = script.replace(_DEFAULT_COMMENT, _GENERIC_COMMENT)
    return script


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Defer <img> images via data-src/data-srcset + IntersectionObserver "
                    "(rootMargin 0px) with a no-observer fallback, byte-faithfully.")
    ap.add_argument('source', metavar='SOURCE.html',
                    help='original HTML file to transform (left untouched)')
    ap.add_argument('image_srcs', metavar='SRC', nargs='+',
                    help='exact img src value(s) to defer, e.g. the Waste and Projects '
                         'quicklink card images: %s and %s'
                         % (WASTE_SRC, PROJECTS_SRC))
    ap.add_argument('--selector', metavar='CSS', default=DEFAULT_SELECTOR,
                    help='CSS selector used by the injected deferral script to find the '
                         'deferred images (default: %r). Use e.g. "img[data-src]" for '
                         'other HTML structures; the script comment becomes generic for '
                         'non-default selectors.' % DEFAULT_SELECTOR)
    ap.add_argument('-o', '--output', metavar='OUT.html',
                    help='write the transformed HTML to this path (default: stdout)')
    ap.add_argument('--verify', metavar='REFERENCE.html',
                    help='after transforming, compare the result byte-for-byte with a '
                         'reference file (e.g. the frozen page) and report match/mismatch')
    args = ap.parse_args(argv)

    with open(args.source, 'rb') as fh:
        data = fh.read()

    src_values = [v.encode('utf-8') for v in args.image_srcs]
    try:
        out, count = defer_images(data, src_values)
    except MissingSourceError as exc:
        print('error: %s' % exc, file=sys.stderr)
        return 1

    try:
        out = insert_defer_script(out, build_defer_script(args.selector))
    except ValueError as exc:
        print('error: %s' % exc, file=sys.stderr)
        return 1

    selector_note = "" if args.selector == DEFAULT_SELECTOR else " (selector: %s)" % args.selector
    if args.output:
        with open(args.output, 'wb') as fh:
            fh.write(out)
        print('deferred %d <img> tag(s), inserted deferral script%s, wrote %s'
              % (count, selector_note, args.output))
    else:
        sys.stdout.buffer.write(out)

    if args.verify:
        with open(args.verify, 'rb') as fh:
            reference = fh.read()
        if out == reference:
            print('verify: OK — output is byte-identical to %s' % args.verify)
        else:
            print('verify: FAIL — output differs from %s' % args.verify, file=sys.stderr)
            return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
