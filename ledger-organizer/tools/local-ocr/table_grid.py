"""Experimental grid-cell mapping for ONE simple straight-line table image."""
import argparse, hashlib, json, math
from pathlib import Path
import cv2
import numpy as np


def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()


def clusters(indices):
    groups=[]
    for idx in indices:
        idx=int(idx)
        if not groups or idx>groups[-1][-1]+1:groups.append([idx])
        else:groups[-1].append(idx)
    return [round(sum(group)/len(group)) for group in groups]


def lines(img):
    gray=cv2.cvtColor(img,cv2.COLOR_BGR2GRAY);h,w=gray.shape
    if min(h,w)<60 or h*w>30000000:raise ValueError('图片尺寸超出实验范围')
    binary=cv2.threshold(gray,0,255,cv2.THRESH_BINARY_INV+cv2.THRESH_OTSU)[1]
    hm=cv2.morphologyEx(binary,cv2.MORPH_OPEN,cv2.getStructuringElement(cv2.MORPH_RECT,(max(20,w//20),1)))
    vm=cv2.morphologyEx(binary,cv2.MORPH_OPEN,cv2.getStructuringElement(cv2.MORPH_RECT,(1,max(20,h//20))))
    ys=clusters(np.flatnonzero((hm>0).sum(axis=1)>w*0.50))
    xs=clusters(np.flatnonzero((vm>0).sum(axis=0)>h*0.45))
    if not (2<=len(xs)<=31 and 2<=len(ys)<=101):raise ValueError('未找到单个完整直线网格，请人工处理')
    if min(np.diff(xs))<15 or min(np.diff(ys))<15:raise ValueError('网格过密或存在多余线条')
    # Require each detected boundary segment; entirely missing lines can remain undetected.
    for y in ys:
        for x1,x2 in zip(xs,xs[1:]):
            area=hm[max(0,y-2):min(h,y+3),x1+3:x2-2]
            if area.size==0 or (area>0).any(axis=0).mean()<0.8:raise ValueError('横向网格不完整或存在合并单元格')
    for x in xs:
        for y1,y2 in zip(ys,ys[1:]):
            area=vm[y1+3:y2-2,max(0,x-2):min(w,x+3)]
            if area.size==0 or (area>0).any(axis=1).mean()<0.8:raise ValueError('纵向网格不完整或存在合并单元格')
    # Detect long partial lines hidden inside inferred cells. This is a conservative
    # guard, not proof that every merged or invisible separator is detectable.
    for y1,y2 in zip(ys,ys[1:]):
        for x1,x2 in zip(xs,xs[1:]):
            inner_v=vm[y1+3:y2-2,x1+4:x2-3]
            inner_h=hm[y1+4:y2-3,x1+3:x2-2]
            if inner_v.size and ((inner_v>0).sum(axis=0)>inner_v.shape[0]*0.70).any():
                raise ValueError('单元格内部出现未识别竖线，可能存在合并或缺失边框')
            if inner_h.size and ((inner_h>0).sum(axis=1)>inner_h.shape[1]*0.70).any():
                raise ValueError('单元格内部出现未识别横线，可能存在合并或缺失边框')
    return xs,ys


def map_table(image, ocrfile, output):
    image=Path(image).resolve();ocrfile=Path(ocrfile).resolve();output=Path(output).resolve()
    if len({str(image),str(ocrfile),str(output)})<3 or output.suffix.lower()!='.json':raise ValueError('输入输出必须是不同文件，输出为 JSON')
    imagehash=sha(image); ocrhash=sha(ocrfile); raw=json.loads(ocrfile.read_text(encoding='utf8'))
    if raw.get('来源sha256')!=imagehash or not isinstance(raw.get('结果'),list):raise ValueError('OCR 结果与原图哈希不一致或格式无效')
    arr=np.fromfile(str(image),dtype=np.uint8);img=cv2.imdecode(arr,cv2.IMREAD_COLOR)
    if img is None:raise ValueError('无法读取图片')
    xs,ys=lines(img);cells=[]
    for ri,(y1,y2) in enumerate(zip(ys,ys[1:]),1):
        for ci,(x1,x2) in enumerate(zip(xs,xs[1:]),1):cells.append({'行':ri,'列':ci,'边界_像素':[x1,y1,x2,y2],'片段':[],'复核状态':'待人工核对原图'})
    unassigned=[]
    for item in raw['结果']:
        box=item.get('位置_像素');text=item.get('识别文本')
        if not isinstance(box,list) or len(box)!=4 or not isinstance(text,str):raise ValueError('OCR 识别框格式无效')
        try:
            bx=[float(p[0]) for p in box];by=[float(p[1]) for p in box]
        except (TypeError,ValueError,IndexError):raise ValueError('OCR 坐标无效')
        if not all(math.isfinite(v) for v in bx+by):raise ValueError('OCR 坐标无效')
        # Entire polygon bounding box must sit strictly within a single cell.
        matches=[c for c in cells if min(bx)>c['边界_像素'][0] and max(bx)<c['边界_像素'][2] and min(by)>c['边界_像素'][1] and max(by)<c['边界_像素'][3]]
        fragment={'识别文本':text,'位置_像素':box,'复核状态':'待人工核对原图'}
        if len(matches)==1:matches[0]['片段'].append(fragment)
        else:unassigned.append(fragment)
    for c in cells:
        c['片段'].sort(key=lambda q:(min(v[1] for v in q['位置_像素']),min(v[0] for v in q['位置_像素'])))
        c['识别文本']=' '.join(x['识别文本'] for x in c['片段'])
    if sha(image)!=imagehash or sha(ocrfile)!=ocrhash:raise ValueError('输入文件在处理期间发生变化')
    data={'用途':'仅虚构样例，自动网格及所有识别结果均须人工复核；空白格不代表原图为空',
          '来源文件名':image.name,'来源sha256':imagehash,'OCR结果sha256':ocrhash,
          '行数':len(ys)-1,'列数':len(xs)-1,'单元格':cells,'未归属片段':unassigned}
    with open(output,'x',encoding='utf8') as f:json.dump(data,f,ensure_ascii=False,indent=2)
    return len(cells),len(unassigned)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('image');p.add_argument('ocr_json');p.add_argument('output');a=p.parse_args()
    print('网格单元格、未归属片段:',map_table(a.image,a.ocr_json,a.output))
