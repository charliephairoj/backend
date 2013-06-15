# Create your views here.
import json
import os
import time
import dateutil.parser

from boto.s3.connection import S3Connection
from boto.s3.key import Key
from django.conf import settings
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required

from acknowledgements.models import Acknowledgement, Item, Delivery
from auth.models import S3Object


def save_upload(request, filename=None):
    if filename is None:
        filename = "{0}{1}.jpg".format(settings.MEDIA_ROOT,time.time())
    #Save File to disk
    image = request.FILES['image']
    filename = settings.MEDIA_ROOT+str(time.time())+'.jpg' 
    with open(filename, 'wb+' ) as destination:
        for chunk in image.chunks():
            destination.write(chunk)
    return filename

@login_required
def acknowledgement(request, ack_id=0):
    #Get Request
    if request.method == "GET":
        if ack_id == 0:
            params = request.GET
            acks = Acknowledgement.objects.all().order_by('-id')

            if "start_date" in params and "end_date" in params:
                start_date = dateutil.parser.parse(params['start_date'])
                end_date = dateutil.parser.parse(params['end_date'])
                acks = acks.filter(delivery_date__range=[start_date, end_date])
            elif "start_date" in params:
                start_date = dateutil.parser.parse(params['start_date'])
                acks = acks.filter(delivery_date__gte=start_date)
            elif "end_date" in params:
                end_date = dateutil.parser.parse(params['end_date'])
                acks = acks.filter(delivery_date__lte=end_date)
            elif "date" in params:
                date = dateutil.parser.parse(params['date'])
                acks = acks.filter(delivery_date=date)
            if "last_modified" in params:
                timestamp = dateutil.parser.parse(params["last_modified"])
                acks = acks.filter(last_modified__gte=timestamp)

            data = [ack.get_data() for ack in acks]
        else:
            ack = Acknowledgement.objects.get(id=ack_id)
            data = ack.get_data()

        response = HttpResponse(json.dumps(data), mimetype="application/json")
        return response

    if request.method == "POST":
        if ack_id == 0:
            data = json.loads(request.body)
            acknowledgement = Acknowledgement.create(data, request.user)
            response_data = acknowledgement.get_data()
            response_data["acknowledgement_url"] = acknowledgement.generate_url('acknowledgement')
            response_data["production_url"] = acknowledgement.generate_url('production')
            return HttpResponse(json.dumps(response_data), mimetype="application/json")
        else:
            data = json.loads(request.body)
            acknowledgement = Acknowledgement.objects.get(id=ack_id)
            acknowledgement.update(data, request.user)
            response_data = acknowledgement.get_data()
            response_data["acknowledgement_url"] = acknowledgement.generate_url('acknowledgement')
            response_data["production_url"] = acknowledgement.generate_url('production')
            return HttpResponse(json.dumps(response_data), mimetype="application/json")


@login_required
def item(request, ack_item_id=0):
    #Get Request
    if request.method == "GET":
        if ack_item_id == 0:
            params = request.GET
            items = Item.objects.all()
            if "status" in params:
                if params["status"] == 'available':
                    items = items.exclude(status='SHIPPED')
                    items = items.exclude(status='ACKNOWLEDGED')
            data = [item.get_data() for item in items]
        else:
            data = Item.objects.get(id=ack_item_id).get_data()
        response = HttpResponse(json.dumps(data), mimetype="application/json")
        return response

    if request.method == "POST":
        if ack_item_id == 0:
            pass
        else:
            data = json.loads(request.body)
            item = Item.objects.get(id=ack_item_id)
            item.update(data, request.user)
            acknowledgement = item.acknowledgement
            acknowledgement.update()
            return HttpResponse(json.dumps(item.get_data()), mimetype="application/json")


@login_required
def log(request, ack_id=0):
    if request.method == "GET":
        if ack_id != 0:
            try:
                data = [log.get_data() for log in Acknowledgement.objects.get(id=ack_id).acknowledgementlog_set.all()]
            except Acknowledgement.DoesNotExist:
                raise Exception
            return HttpResponse(json.dumps(data), mimetype="application/json")


@login_required
def pdf(request, ack_id):
    if "type" in request.GET:
        acknowledgement = Acknowledgement.objects.get(id=ack_id)
        if request.GET["type"] == "acknowledgement":
            url = acknowledgement.generate_url('acknowledgement')
        elif request.GET["type"] == "production":
            url = acknowledgement.generate_url('production')
        data = {'url': url}
        return HttpResponse(json.dumps(data), mimetype="application/json")


@login_required
def acknowledgement_item_image(request):
    if request.method == "POST":
        filename = save_upload(request)
        obj = S3Object.create(filename,
                        "acknowledgement/item/image/{0}.jpg".format(time.time()),
                        'media.dellarobbiathailand.com')
        response = HttpResponse(json.dumps({'id': obj.id,
                                            'url': obj.generate_url()}),
                                content_type="application/json")
        response.status_code = 201
        return response


@login_required
def delivery(request):
    if request.method == "GET":
        data = [d.get_data() for d in Delivery.objects.all()]
        response = HttpResponse(json.dumps(data), mimetype="application/json")
        response.status_code = 201
        return response
        
        
        
        
