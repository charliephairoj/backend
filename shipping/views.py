# Create your views here.
import json

from django.http import HttpResponse

from shipping.models import Shipping
from acknowledgements.models import Acknowledgement

def shipping(request):
    
    #Get Request
    if request.method == "GET":
        data = []
        for ack in Shipping.objects.all().order_by('-id'):
            
            data.append(ack.get_data())
        
        response = HttpResponse(json.dumps(data), mimetype="application/json")
        return response

    if request.method == "POST":
        data = json.loads(request.body)
        ack = Shipping()
        urls = ack.create(data, user=request.user)
        data = urls.update(ack.get_data())
        return HttpResponse(json.dumps(urls), mimetype="application/json")
    
#Get url
def acknowledgement_url(request, ack_id=0):
    if ack_id != 0 and request.method == "GET":
        ack = Acknowledgement.object.get(id=ack_id)


def acknowledgement_item_image(request):
    
    
    if request.method == "POST":
        import os
        import time
        from django.conf import settings
        from boto.s3.connection import S3Connection
        from boto.s3.key import Key
        
        image = request.FILES['image']
        filename = settings.MEDIA_ROOT+str(time.time())+'.jpg'
           
        with open(filename, 'wb+' ) as destination:
            for chunk in image.chunks():
                destination.write(chunk)
        #start connection
        conn = S3Connection(settings.AWS_ACCESS_KEY_ID, settings.AWS_SECRET_ACCESS_KEY)
        #get the bucket
        bucket = conn.get_bucket('media.dellarobbiathailand.com', True)
        #Create a key and assign it 
        k = Key(bucket)
                
        #Set file name
        k.key = "acknowledgement/item/image/%f.jpg" % (time.time())
        #upload file
            
        k.set_contents_from_filename(filename)
            
        #remove file from the system
        os.remove(filename)
        #set the Acl
        k.set_canned_acl('private')
         
        #set Url, key and bucket
        data = {
                'url':k.generate_url(300, force_http=True),
                'key':k.key,
                'bucket':'media.dellarobbiathailand.com'
        }
            
        #self.save()
        response = HttpResponse(json.dumps(data), mimetype="application/json")
        response.status_code = 201
        return response
        