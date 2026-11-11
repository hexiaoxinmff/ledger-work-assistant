"""Render all pages of a small local PDF to PNG with a provenance manifest."""
import argparse,hashlib,json,math,os
from pathlib import Path
import pypdfium2 as pdfium

def sha(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()

def run(source,output_dir,dpi=120):
 source=Path(source).resolve();out=Path(output_dir).resolve()
 if source.suffix.lower()!='.pdf' or not 72<=dpi<=200:raise ValueError('只支持本地 PDF 和 72–200 DPI')
 before=sha(source);doc=pdfium.PdfDocument(str(source))
 try:
  count=len(doc)
  if not 1<=count<=20:raise ValueError('仅支持 1 至 20 页的试验文件')
  sizes=[]
  for i in range(count):
   page=doc[i]
   try:
    w,h=page.get_size();pw=math.ceil(w*dpi/72);ph=math.ceil(h*dpi/72)
    if pw<1 or ph<1 or pw*ph>25000000:raise ValueError('页面尺寸超出限制')
    sizes.append((pw,ph))
   finally:page.close()
  os.mkdir(out) # Exclusive; a failure may leave partial files for review.
  pages=[]
  for i in range(count):
   page=doc[i];bitmap=None
   try:
    bitmap=page.render(scale=dpi/72);image=bitmap.to_pil().convert('RGB');name=f'page_{i+1:04d}.png';path=out/name
    with open(path,'xb') as f:image.save(f,format='PNG')
    pages.append({'page':i+1,'image':name,'sha256':sha(path),'width':image.width,'height':image.height})
   finally:
    if bitmap is not None:bitmap.close()
    page.close()
  if sha(source)!=before:raise ValueError('PDF 在处理期间变化')
  manifest={'source_name':source.name,'source_sha256':before,'dpi':dpi,'page_count':count,'pages':pages,'status':'所有页面及数字均需人工核对'}
  with open(out/'pages.json','x',encoding='utf8') as f:json.dump(manifest,f,ensure_ascii=False,indent=2)
  return count
 finally:doc.close()

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('pdf');p.add_argument('output_dir');p.add_argument('--dpi',type=int,default=120);a=p.parse_args();print('已渲染页数:',run(a.pdf,a.output_dir,a.dpi))
