"""Experimental local OCR for a single image. All results require human verification."""
import argparse, hashlib, importlib.metadata as metadata, importlib.util, json, os, socket
from pathlib import Path

EXPECTED_MODELS={
 "PP-OCRv6_det_small.onnx":"090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f",
 "ch_ppocr_mobile_v2.0_cls_mobile.onnx":"e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c",
 "PP-OCRv6_rec_small.onnx":"6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884",
}

def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()

def check_runtime():
    if metadata.version('rapidocr')!='3.10.0' or metadata.version('onnxruntime')!='1.20.1':raise ValueError('当前试用版仅测试 rapidocr 3.10.0 与 onnxruntime 1.20.1')
    spec=importlib.util.find_spec('rapidocr')
    if spec is None or spec.origin is None:raise ValueError('未发现 rapidocr')
    model_dir=Path(spec.origin).parent/'models'
    for filename,expected in EXPECTED_MODELS.items():
        model=model_dir/filename
        if not model.is_file() or sha(model)!=expected:raise ValueError('本地模型缺失或哈希不符：'+filename)
    return {'versions':{'rapidocr':'3.10.0','onnxruntime':'1.20.1'},'models_verified':list(EXPECTED_MODELS),'note':'仅校验版本与模型文件哈希；未初始化引擎或验证识别效果'}

def run(source, output):
    source=Path(source).resolve(); output=Path(output).resolve()
    if source==output:raise ValueError('输出不能覆盖源文件')
    if output.suffix.lower() != '.json':raise ValueError('输出必须是 JSON 文件')
    if source.suffix.lower() not in ('.png','.jpg','.jpeg'):raise ValueError('仅支持本地 PNG/JPEG 图片，不支持 PDF')
    check_runtime()
    before=sha(source)
    # Block Python socket connections inside this short-lived process. This is not OS isolation.
    def deny(*args,**kwargs):raise OSError('OCR test: network access disabled')
    socket.socket.connect=deny;socket.socket.connect_ex=deny
    from rapidocr import RapidOCR
    result=RapidOCR()(str(source)); records=[]
    if result is not None and result.txts is not None:
        texts=list(result.txts); boxes=list(result.boxes); scores=list(result.scores)
        if not len(texts)==len(boxes)==len(scores):raise ValueError('识别字段数量不一致')
        for text,box,score in zip(texts,boxes,scores):
            records.append({'识别文本':str(text),'位置_像素':[[round(float(x),2),round(float(y),2)] for x,y in box],
                            '模型分数':round(float(score),4),'复核状态':'待人工核对原图'})
    if sha(source)!=before:raise ValueError('原图在识别期间变化，结果不可交付')
    data={'用途':'虚构图片试用，识别数字须逐字符人工核对；不自动入账或配对',
          '来源文件名':source.name,'来源sha256':before,'识别引擎':'RapidOCR 3.10.0 / ONNX Runtime 1.20.1',
          '网络':'本进程拦截 Python socket 连接，不代表操作系统级隔离',
          '结果':records}
    with open(output,'x',encoding='utf8') as f:json.dump(data,f,ensure_ascii=False,indent=2)
    return len(records)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',nargs='?');p.add_argument('output',nargs='?');p.add_argument('--check-runtime',action='store_true');a=p.parse_args()
    if a.check_runtime:
        if a.source or a.output:p.error('--check-runtime 不接收输入或输出文件')
        print(json.dumps(check_runtime(),ensure_ascii=False))
    else:
        if not a.source or not a.output:p.error('识别需要 source 和 output')
        print('识别行数（均需人工复核）:',run(a.source,a.output))
