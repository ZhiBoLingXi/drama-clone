import re,sys
from docx import Document
from docx.shared import Pt, RGBColor
from docx.oxml.ns import qn
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
src,out=sys.argv[1],sys.argv[2]
FONT='宋体'
doc=Document()
def setfont(style,size,bold=False):
    st=doc.styles[style]; st.font.name=FONT; st.font.size=Pt(size); st.font.bold=bold
    st.font.color.rgb=RGBColor(0,0,0)
    st.element.rPr.rFonts.set(qn('w:eastAsia'),FONT)
setfont('Normal',11); setfont('Title',20,True); setfont('Heading 1',16,True)
doc.styles['Normal'].paragraph_format.space_after=Pt(3)
doc.styles['Normal'].paragraph_format.line_spacing=1.25
def run(p,text,bold=False):
    r=p.add_run(text); r.bold=bold; r.font.name=FONT; r._element.rPr.rFonts.set(qn('w:eastAsia'),FONT); return r
first=True; n_ep=0
for line in open(src,encoding='utf-8').read().splitlines():
    line=line.rstrip()
    if not line: continue
    if line.startswith('# 《'):
        p=doc.add_paragraph(style='Title'); p.alignment=WD_ALIGN_PARAGRAPH.CENTER; run(p,line[2:],True); continue
    if line.startswith('## '):
        h=doc.add_heading(level=1); run(h,line[3:],True); continue
    m=re.match(r'^# (第.+集)$',line)
    if m:
        if not first: doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
        first=False; n_ep+=1
        h=doc.add_heading(level=1); run(h,m.group(1),True); continue
    p=doc.add_paragraph()
    if line.startswith('场'):
        p.paragraph_format.space_before=Pt(8); run(p,line,True)
    elif line.startswith('人物：'):
        run(p,'人物：',True); run(p,line[3:])
    elif line.startswith('△'):
        run(p,line)
    else:
        m=re.match(r'^([^：（]{1,20})((?:（[^）]*）)?)：(.*)$',line)
        if m:
            run(p,m.group(1),True);
            if m.group(2): run(p,m.group(2))
            run(p,'：'+m.group(3))
        else: run(p,line)
doc.save(out); print('episodes',n_ep)
