"""PDF-only background covers for reviewed fixed-roast text regions.

Source image bytes are never changed. Small vector cells interpolate the
background immediately above/below each region, avoiding a visible black bar.
"""
import io,math
from PIL import Image
from .artwork_rules import validate_masks


def cover_fixed_roast(canvas,raw,masks,left,bottom,width,height):
    validate_masks(masks)
    with Image.open(io.BytesIO(raw)) as image:
        image=image.convert('RGB');iw,ih=image.size
        canvas.saveState()
        for mask in masks:
            mx,my,mw,mh=(mask[k] for k in ('x','y','w','h'))
            columns=min(128,max(1,math.ceil(mw*iw/3)));bands=min(24,max(4,math.ceil(mh*ih/2)))
            above=max(0,int(my*ih)-2);below=min(ih-1,math.ceil((my+mh)*ih)+1)
            for col in range(columns):
                px=min(iw-1,max(0,int((mx+mw*(col+.5)/columns)*iw)))
                top=image.getpixel((px,above));low=image.getpixel((px,below))
                for band in range(bands):
                    ratio=(band+.5)/bands
                    canvas.setFillColorRGB(*(round((a+(b-a)*ratio)/255,5) for a,b in zip(top,low)))
                    canvas.rect(left+(mx+mw*col/columns)*width,
                                bottom+(1-my-mh*(band+1)/bands)*height,
                                mw*width/columns,mh*height/bands,stroke=0,fill=1)
        canvas.restoreState()
