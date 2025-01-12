import aiohttp
import asyncio
import uvicorn
import random
from fastai import *
from fastai.text import *
from io import BytesIO, StringIO
import matplotlib.cm as cm
from tika import parser
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import HTMLResponse, JSONResponse
from starlette.staticfiles import StaticFiles
import os
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import (
    Mail, Attachment, FileContent, FileName,
    FileType, Disposition, ContentId)
from datetime import datetime, timedelta
import csv
import base64
import json

export_file_url = 'https://qz-aistudio-jbfm-scratch.s3.amazonaws.com/final_no_preds_export.pkl'
export_file_name = 'final_no_preds_export.pkl'

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
        learn = load_learner('app/', export_file_name,test) # Replace path with path of file
        # learn.model = learn.model.module # must reference module since the learner was wrapped in nn.DataParallel
#         preds = learn.get_preds(ds_type=DatasetType.Test)
#         logger.info("learner set up successfully")
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

# Remove front-end
# @app.route('/')
# async def homepage(request):
#    html_file = path / 'view' / 'index.html'
#    return HTMLResponse(html_file.open().read())

@app.route('/healthz', methods=['GET'])
async def health_check(request):
    return JSONResponse({'health_check': 'ok'})

@app.route('/analyze', methods=['POST'])
async def predict(request):
    pdf_data = await request.form()
    if 'reports' in pdf_data:
        reports = pdf_data['reports'] # Get list of reports and school names
        reports = json.loads(reports)
        print (reports)
    if 'to_email' in pdf_data:
        sendEmail = True
        to_email = pdf_data['to_email']
        from_email = pdf_data['from_email']

    try:
        yesterday = datetime.strftime(datetime.now() - timedelta(1), '%Y-%m-%d')
        csv_name = 'app/school-closures'+yesterday+'.csv'
        print (csv_name)
        with open(csv_name,'w') as csv_file:
            csv_writer = csv.writer(csv_file, delimiter=',', quotechar='"',quoting=csv.QUOTE_MINIMAL)
            csv_writer.writerow(['school','report','confidence'])
            print ("wrote to csv")
            for obj in reports:
                school = obj['school']
                my_file = obj['file']
                print ("parsing file...")
                text = parser.from_file(my_file)['content'] # Pull down file from link
                text = text.replace('\n',' ')
                prediction = learn.predict(text)
                print (prediction)
                print ("prediction made")
                tensor_label = prediction[1].item()
                if tensor_label == 0:
                    prob = prediction[2][0].item()
                    res = "Result: " + str(prediction[0]) + " - this school may be in danger of closing"
                else:
                    prob = prediction[2][1].item()
                    res = "Result: " + str(prediction[0]) + " - this school is not in danger of closing"
                print ("printing prob..."+str(prob))
                if str(prediction[0]) == 'last':
                    csv_writer.writerow([school, my_file, prob])
                    csv_file.flush()
            csv_file.close()

    except Exception as e:
        res = "Sorry, we ran into an error! Please check the file type of the report you submitted. This app only supports .pdf and .txt files."
        print ("error making predictions")
        print (e)
        sendEmail = False
        raise
        return JSONResponse({'result': res})
    finally:
        if sendEmail == True: # if sendEmail == True, send email with Twilio
            content = "Hey there! We ran into some interesting school reports from Ofsted, and by our calculations, these could possibly be the final reports of these schools before they close. We've attached a CSV with a list of the school reports."
            try:
                with open(csv_name,'rb') as f: # open up the csv and attach it
                    data = f.read()
                    f.close()
                encoded = base64.b64encode(data).decode() # encode csv file to send attachment
                attachment = Attachment()
                attachment.content = encoded
                attachment.file_content = FileContent(encoded)
                attachment.file_name = csv_name
                attachment.disposition = Disposition('attachment')
                attachment.file_type = FileType("text/csv")

                message = Mail(
                from_email=from_email,
                to_emails=to_email,
                subject='Predicting School Closures '+yesterday,
                html_content=content
                )
                message.attachment = attachment
                sg = SendGridAPIClient(os.environ.get('apiKey'))
                response = sg.send(message)
                print (response.status_code)
                print (response.body)
                print (response.headers)
            except Exception as e:
                print ("could not send email")
                print(str(e))
                return JSONResponse({'result': 'Email could not be sent'})

        os.remove(csv_name) # delete the csv file

        return JSONResponse({'result': 'Email sent'})

if __name__ == '__main__':
    if 'serve' in sys.argv: uvicorn.run(app=app, host='0.0.0.0', port=5042, log_level="info", timeout_keep_alive=10800)
