# Defense deck generator

`../CANvisionNative_defense.pptx` is generated from `build.js` (pptxgenjs) and `hero.js` (the eye
emblem). `post.py` then adds the Morph transitions, the dark colour map and the slide animations
that `build.js` describes in `anim.json`.

```
npm install pptxgenjs react-icons react react-dom sharp
set NODE_PATH=%CD%\node_modules
node build.js
python post.py ..\CANvisionNative_defense.pptx
```

PDF backup: build a print variant that keeps only the final state of each slide (elements removed
by an exit animation are left out), post-process it without animations, then export it to PDF
from PowerPoint.

```
set PRINT=1
node build.js print.pptx
python post.py print.pptx none
```

Rebuilding overwrites the .pptx, including anything edited by hand in PowerPoint (for example an
inserted demo video). Edit `build.js` first, or re-insert the video after.
