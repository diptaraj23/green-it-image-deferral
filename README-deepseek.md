# defer_images_deepseek.py

Reusable, standard-library-only Python script that **independently reproduces the
image deferral** implemented in
`webpage/optimized/deepseek/differdange-environment-local.html` (the frozen
DeepSeek optimised page).

Given the original
`webpage/differdange-environment-local.html` and the two exact image `src`
values for the **Waste** and **Projects** quicklink cards, it produces the same
page the frozen DeepSeek file shows:

- the Waste and Projects `<img>` tags get `src` → `data-src` (and `srcset` →
  `data-srcset` where present);
- a deferral script is inserted right before `</body>`:
  `data-src`/`data-srcset` plus an `IntersectionObserver` with
  `rootMargin: '0px'`, and a no-observer fallback that loads the images
  immediately;
- every other byte of the original HTML is preserved, and the source file and
  site assets are never touched (output goes to `--output`, default stdout).

## Usage

```bash
python3 tools/defer_images_deepseek.py \
  webpage/differdange-environment-local.html \
  ./differdange-environment-local_files/dechets.png \
  ./differdange-environment-local_files/netzerocities-528x388.jpg \
  -o /tmp/differdange-environment-local-deferred.html
```

Any number of `SRC` values may be given; each is rewritten only on `<img>` tags.
The frozen page `webpage/optimized/deepseek/differdange-environment-local.html`
is kept as the verification reference (see below), so write the output to a
fresh path rather than overwriting it.

### Custom selector for other HTML structures

The injected script finds the deferred images with
`.pagequicklinks img[data-src]` by default — that is the quicklink-card
structure of the Differdange page. For pages with a different structure pass
`--selector`:

```bash
python3 tools/defer_images_deepseek.py /tmp/sample.html img/a.png img/b.jpg \
  --selector 'img[data-src]' -o /tmp/sample-deferred.html
```

The selector string inside `document.querySelectorAll(...)` is replaced and the
script comment becomes generic (`/* Defer the below-the-fold images until they
enter the viewport. */`), while the IntersectionObserver (`rootMargin: '0px'`)
and no-observer fallback logic stay unchanged. Without `--selector` the
injected script remains byte-for-byte identical to the one in the frozen page.

## Verification

1. **Byte-for-byte check against the frozen page**

   ```bash
   python3 tools/defer_images_deepseek.py \
     webpage/differdange-environment-local.html \
     ./differdange-environment-local_files/dechets.png \
     ./differdange-environment-local_files/netzerocities-528x388.jpg \
     -o /tmp/out-deferred.html \
     --verify webpage/optimized/deepseek/differdange-environment-local.html
   ```

   Expect `verify: OK — output is byte-identical to …`. (The earlier
   implementation `webpage/optimized/differdange-environment-local.html` is
   intentionally not part of this check.)

2. **Preservation of untouched bytes**

   ```bash
   cmp /tmp/out-deferred.html webpage/optimized/deepseek/differdange-environment-local.html
   ```

   Must exit silently with status 0.

3. **Novel sample image — transform with a custom selector**

   The sample has no `.pagequicklinks` wrapper, so the default selector would
   never match. Defer it with `--selector 'img[data-src]'`:

   ```bash
   printf '%s\n' '<!DOCTYPE html><html><body>' \
     '<img src="img/a.png" srcset="img/a.png 1x, img/a-2x.png 2x" alt="A">' \
     '<img src="img/b.jpg" alt="B">' \
     '</body></html>' > /tmp/sample.html

   python3 tools/defer_images_deepseek.py /tmp/sample.html img/a.png img/b.jpg \
     --selector 'img[data-src]' -o /tmp/sample-deferred.html
   ```

   Text checks on `/tmp/sample-deferred.html`:

   - the first image reads `data-src="img/a.png"` with `data-srcset=…`, the
     second `data-src="img/b.jpg"`;
   - the injected script contains `document.querySelectorAll('img[data-src]')`
     and the generic comment, and appears directly before `</body>`.

#### Loader behaviour check (DOM/IntersectionObserver stub)

Text checks above prove nothing about whether the images actually load when
scrolled. This check executes the injected script against a minimal DOM +
IntersectionObserver stub (macOS JavaScriptCore via `osascript`, no Node
needed) to confirm: images start deferred (no `src`, only `data-src`), load
when their `IntersectionObserver` entry reports `isIntersecting`, and the
no-observer fallback loads everything immediately.

```bash
cat > /tmp/defer-harness.js <<'EOF'
ObjC.import("Foundation");
function readFile(p){var d=$.NSFileManager.defaultManager.contentsAtPath(p);
  return $.NSString.alloc.initWithDataEncoding(d,$.NSUTF8StringEncoding).js;}
function makeImg(attrs){var a={};attrs.forEach(function(p){a[p[0]]=p[1];});
  return{attrs:a,getAttribute:function(n){return Object.prototype.hasOwnProperty.call(a,n)?a[n]:null;},
  setAttribute:function(n,v){a[n]=String(v);},removeAttribute:function(n){delete a[n];}};}
function parseAttrs(t){var o=[],m=/([A-Za-z-]+)="([^"]*)"/g,x;while((x=m.exec(t)))o.push([x[1],x[2]]);return o;}
function readImgs(h){var t=[],re=/<img\b[^>]*>/g,m;while((m=re.exec(h)))t.push(m[0]);
  return t.map(function(x){return makeImg(parseAttrs(x));});}
function Stub(cb,opts){this.cb=cb;this.opts=opts;this.observed=[];this.unobserved=[];}
Stub.prototype.observe=function(t){this.observed.push(t);};
Stub.prototype.unobserve=function(t){this.unobserved.push(t);};
Stub.prototype.fire=function(es){this.cb(es);};
function assert(c,msg){if(!c)throw new Error("FAIL: "+msg);}
var html=readFile("/tmp/sample-deferred.html");
var m=html.match(/<script>\n\/\* Defer[\s\S]*?\n<\/script>/);assert(m,"script missing");
var code=m[0].replace(/^<script>\n/,"").replace(/\n<\/script>$/,"");
var imgs=readImgs(html),io=null;
globalThis.document={querySelectorAll:function(s){return s==="img[data-src]"?
  imgs.filter(function(i){return i.getAttribute("data-src")!==null;}):[];}};
globalThis.IntersectionObserver=function(cb,opts){io=new Stub(cb,opts);return io;};
globalThis.window={IntersectionObserver:globalThis.IntersectionObserver};
new Function(code)();
assert(imgs[0].getAttribute("src")===null,"imgA not deferred");
assert(imgs[1].getAttribute("src")===null,"imgB not deferred");
assert(io.observed.length===2,"images not observed");
assert(io.opts.rootMargin==="0px","rootMargin not 0px");
io.fire([{isIntersecting:true,target:imgs[0]},{isIntersecting:false,target:imgs[1]}]);
assert(imgs[0].getAttribute("src")==="img/a.png","imgA did not load on scroll");
assert(imgs[0].getAttribute("data-src")===null,"imgA data-src not removed");
assert(imgs[1].getAttribute("src")===null,"imgB loaded below the fold");
io.fire([{isIntersecting:true,target:imgs[1]}]);
assert(imgs[1].getAttribute("src")==="img/b.jpg","imgB did not load on scroll");
var imgs2=readImgs(html);
globalThis.document={querySelectorAll:function(s){return s==="img[data-src]"?
  imgs2.filter(function(i){return i.getAttribute("data-src")!==null;}):[];}};
delete globalThis.IntersectionObserver;globalThis.window={};
new Function(code)();
assert(imgs2[0].getAttribute("src")==="img/a.png","fallback did not load imgA");
assert(imgs2[1].getAttribute("src")==="img/b.jpg","fallback did not load imgB");
"PASS: loader behaviour verified (observer + fallback)";
EOF
osascript -l JavaScript /tmp/defer-harness.js
```

Must print `PASS: loader behaviour verified (observer + fallback)`. (With Node
installed, the same harness runs as `node /tmp/defer-harness.js` after
replacing the `ObjC`/`readFile` lines with `fs.readFileSync`.)

#### Missing-source error

```bash
python3 tools/defer_images_deepseek.py /tmp/sample.html img/a.png no-such-image.png; echo "exit=$?"
```

Must print `error: image src not found: 'no-such-image.png' …` to stderr and
exit with a non-zero status without writing any output.

## Method (as in the frozen page)

```javascript
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
```
