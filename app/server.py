import aiohttp
import asyncio
import uvicorn
import random
from fastai import *
from fastai.text import *
from io import BytesIO
import matplotlib.cm as cm, mpld3
from tika import parser
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import HTMLResponse, JSONResponse
from starlette.staticfiles import StaticFiles

export_file_url = 'https://qz-aistudio-jbfm-scratch.s3.amazonaws.com/export.pkl'
export_file_name = 'export.pkl'

# TODO: Maybe pull most recent reports from Ofsted

classes = ['last', 'not_last']
path = Path(__file__).parent

app = Starlette()
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_headers=['X_Requested-With', 'Content-Type'])
app.mount('/static', StaticFiles(directory='app/static'))

async def download_file(url, dest): # Download the pickled model
    if dest.exists(): return
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            data = await response.read()
            with open(dest, 'wb') as f:
                f.write(data)

async def setup_learner(): # Load learner for predictions
    await download_file(export_file_url, path / export_file_name)
    try:
        test = ItemList.from_csv(path='app/',csv_name='last_report_test_sample.csv')
        learn = load_learner(path, export_file_name,test) # Replace path with path of file
        learn.model = learn.model.module # must reference module since the learner was wrapped in nn.DataParallel
        preds = learn.get_preds(ds_type=DatasetType.Test)
        return learn
    except RuntimeError as e:
        if len(e.args) > 0 and 'CPU-only machine' in e.args[0]:
            print (e)
            message = "\n\nThis model was trained with an old version of fastai and will not work in a CPU environment.\n\nPlease update the fastai library in your training environment and export your model again.\n\nSee instructions for 'Returning to work' at https://course.fast.ai."
            raise RuntimeError(message)
    else:
        raise

loop = asyncio.get_event_loop()
tasks = [asyncio.ensure_future(setup_learner())]
learn = loop.run_until_complete(asyncio.gather(*tasks))[0]
loop.close()

@app.route('/')
async def homepage(request):
    html_file = path / 'view' / 'index.html'
    return HTMLResponse(html_file.open().read())

@app.route('/analyze', methods=['POST'])
async def predict(request):
    pdf_data = await request.form()
    pdf_bytes = await(pdf_data['file'].read())
    pdf = BytesIO(pdf_bytes)
    text = parser.from_buffer(pdf)['content']
    text = text.replace('\n',' ')
    prediction = learn.predict(text)
    tensor_label = prediction[1].item()
    if tensor_label == 0:
        prob = prediction[2][0].item()
        res = str(prediction[0]) + " - this school may be in danger of closing"
    else:
        prob = prediction[2][1].item()
        res = str(prediction[0]) + " - this school is not in danger of closing"
    txt_ci = TextClassificationInterpretation.from_learner(learn=learn,ds_type=DatasetType.Test)
    attention = txt_ci.html_intrinsic_attention(text,cmap=cm.Purples)
    return JSONResponse({'result': res, 'probability': str(prob), 'attention': attention})

if __name__ == '__main__':
    if 'serve' in sys.argv: uvicorn.run(app=app, host='0.0.0.0', port=5042, log_level="info")
