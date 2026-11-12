"""Experimental multi-page PDF to human-review XLSX pipeline."""
import argparse,json,subprocess,sys
from pathlib import Path


def run(pdf,output_dir,embed_previews=False):
 pdf=Path(pdf).resolve();out=Path(output_dir).resolve();here=Path(__file__).resolve().parent
 # render_pdf creates the output directory exclusively; never remove a partial result.
 def step(label,args):
  try:
   result=subprocess.run([sys.executable,str(here/args[0]),*[str(x) for x in args[1:]]],capture_output=True,text=True,encoding='utf8',errors='replace',timeout=120)
  except subprocess.TimeoutExpired as e:raise RuntimeError(label+' 超时；中间文件保留，需检查并换新目录') from e
  if result.returncode:raise RuntimeError(label+' 失败，未生成完整交付；如有中间文件则保留。'+result.stderr[-1500:])
 step('OCR版本与模型预检',['recognize_image.py','--check-runtime'])
 step('PDF逐页渲染',['render_pdf.py',pdf,out])
 manifest=json.loads((out/'pages.json').read_text(encoding='utf8'));count=manifest['page_count']
 for i in range(1,count+1):
  page=out/f'page_{i:04d}.png';ocr=out/f'page_{i:04d}_ocr.json';grid=out/f'page_{i:04d}_grid.json'
  step(f'第{i}页 OCR',['recognize_image.py',page,ocr])
  step(f'第{i}页网格定位',['table_grid.py',page,ocr,grid])
 review=out/'待人工复核.xlsx';args=['export_pdf_review.py',pdf,out,review]
 if embed_previews:args.append('--embed-page-previews')
 step('复核表生成',args);return count,review

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('pdf');p.add_argument('output_dir');p.add_argument('--embed-page-previews',action='store_true');a=p.parse_args()
 count,path=run(a.pdf,a.output_dir,a.embed_page_previews);print('已处理页数:',count,'复核表:',path,'所有内容需人工核对原件')
