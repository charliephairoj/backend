"""
API file for acknowledgements
"""
import logging 
import dateutil

from tastypie import fields
from tastypie.resources import ModelResource
from tastypie.authorization import Authorization, DjangoAuthorization
from administrator.models import User
from django.db.models import Q
import pytz

from acknowledgements.models import Acknowledgement, Item, Log
from acknowledgements.validation import AcknowledgementValidation
from contacts.models import Customer
from supplies.models import Fabric
from media.models import S3Object
from projects.models import Project

logger = logging.getLogger(__name__)

        
class AcknowledgementResource(ModelResource):
    items = fields.ToManyField('acknowledgements.api.ItemResource', 'items', 
                               readonly=True, null=True, full=True)
    customer = fields.ToOneField('contacts.api.CustomerResource', 'customer',
                                 readonly=True, full=True)
    
    class Meta:
        queryset = Acknowledgement.objects.filter(deleted=False).order_by('-id')
        resource_name = 'acknowledgement'
        allowed_methods = ['get', 'post', 'put', 'patch']
        fields = ['time_created', 'deleted', 'last_modified', 'po_id', 'subtotal', 'vat', 'total', 
                  'remarks', 'status', 'delivery_date', 'id']
        always_return_data = True
        validation = AcknowledgementValidation()
        authorization = DjangoAuthorization()
        format = 'json'
        
    def dehydrate(self, bundle):
        """
        Implements the dehydrate method
        
        Adds the urls for the acknowledgement and
        the production pdf to the data
        """
        #Add URLS for the acknowledgement
        #and the production pdf to the data
        #bundle
        if bundle.request.GET.get('pdf'):
            try:
                ack = bundle.obj.acknowledgement_pdf
                production = bundle.obj.production_pdf
                bundle.data['pdf'] = {'acknowledgement': ack.generate_url(),
                                      'production': production.generate_url()}
            except AttributeError as e:
                logger.warn(e) 
                logger.warn('Missing acknowledgement or production pdf')
            
            try:
                label = bundle.obj.label_pdf
                bundle.data['pdf']['label'] = label.generate_url()
            except AttributeError:
                logger.warn("Missing label pdf")
                
        #Adds a dictionary for the project if it exists
        if bundle.obj.project:
            bundle.data['project'] = {'id': bundle.obj.project.id,
                                      'codename': bundle.obj.project.codename}
                                      
        return bundle
    
    def apply_filters(self, request, applicable_filters):
        obj_list = super(AcknowledgementResource, self).apply_filters(request, applicable_filters)
        
        
        if request.GET.has_key('q'):
            query = request.GET.get('q')
            obj_list = obj_list.filter(Q(customer__name__icontains=query) | 
                                       Q(pk__icontains=query))
        return obj_list
    
    def obj_create(self, bundle, **kwargs):
        """
        Creates the acknowledgement resource
        """
        logger.info("Creating a new acknowledgement...")
        #Create the object
        bundle.obj = Acknowledgement()
        #hydrate
        bundle = self.full_hydrate(bundle)
        
        #Set the customer
        try:
            logger.info("Setting customer...")
            bundle.obj.customer = Customer.objects.get(pk=bundle.data["customer"]["id"])
            bundle.obj.discount = bundle.obj.customer.discount
        except:
            logger.error("Customer with ID {0} could not be found.".format(bundle.data['customer']['id']))
            raise
        
        #Set the employee
        try:
            logger.info("Setting employee...")
            bundle.obj.employee = bundle.request.user
        except User.DoesNotExist:
            logger.error("User with ID {0} could not be found".format(bundle.data['employee']['id']))
            raise
        except KeyError:
            logger.critical("Missing employee ID.")
            raise
        
        #Set Status
        bundle.obj.status = "ACKNOWLEDGED"
        
        #Set the project or create a new one
        if "project" in bundle.data:
            try:
                project = Project.objects.get(pk=bundle.data['project']['id'])
            except KeyError, Project.DoesNotExist:
                try:
                    project = Project()
                    project.codename = bundle.data['project']['codename']
                    project.save()
                except KeyError:
                    project = None
                
            bundle.obj.project = project
            
        #Create items without saving them 
        logger.info("Creating items...")
        self.items = [Item.create(acknowledgement=bundle.obj,
                                  commit=False,
                                  **product) for product in bundle.data["items"]]
        
        #Calculate the total price
        logger.info("Calculating balance of the order...")
        bundle.obj.calculate_totals(self.items)
        bundle = self.save(bundle)
        
        #Save the items
        logger.info("Saving the items to the database...")
        for item in self.items:
            item.acknowledgement = bundle.obj
            item.save()
        
        log_message = "Ack {0} created on {1}. Schedule to be delivered on {1}"
        log_message = log_message.format(bundle.obj.id,
                                         bundle.obj.time_created.strftime('%B %d, %Y'),
                                         bundle.obj.delivery_date.strftime('%B %d, %Y'))
        log = Log(message=log_message,
                  delivery_date=bundle.obj.delivery_date,
                  acknowledgement=bundle.obj)
        log.save()
        #Create and upload the pdfs to the 
        #S3 system. The save the pdfs as
        #Attributes of the acknowledgement
        logger.info("Creating PDF documents...")
        bundle.obj.create_and_upload_pdfs()
        
        
        #Add the url of the pdf to the outgoing data
        #only for when an acknowledgement is create
        try:
            ack = bundle.obj.acknowledgement_pdf
            production = bundle.obj.production_pdf
            bundle.data['pdf'] = {'acknowledgement': ack.generate_url(),
                                  'production': production.generate_url()}
        except AttributeError: 
            logger.warn('Missing acknowledgement or production pdf')
        
        #Conditionally email ack to Decoroom
        if "decoroom" in bundle.obj.customer.name.lower():
            try:
                logger.info("Emailing Decoroom Co., Ltd. the order details...")
                bundle.obj.email_decoroom()
            except Exception as e:
                logger.error("Unable to mail decoroom.")
                logger.error(e)
        
        
             
        logger.info(u"Acknowledgement #{0} created for {1}".format(bundle.obj.id, 
                                                                  bundle.obj.customer.name)) 
        return bundle
    
    def obj_update(self, bundle, **kwargs):
        """
        Implements the obj_update method
        """
        logger.info("Updating acknowledgement...")
            
        bundle = super(AcknowledgementResource, self).obj_update(bundle, **kwargs)
        
        bundle.obj.create_and_upload_pdfs()
        
        return bundle
    
    def obj_delete(self, bundle, **kwargs):
        """
        Implements the obj_delete method
        """
        logger.info("Deleting acknowledgement...")
        super(AcknowledgementResource, self).obj_delete(bundle, **kwargs)
        

class ItemResource(ModelResource):    
    
    class Meta:
        queryset = Item.objects.all()
        resource_name = 'acknowledgement-item'
        allowed_methods = ['get', 'put', 'patch']
        always_return_data = True
        authorization = DjangoAuthorization()
        
    def hydrate(self, bundle):
        """
        Implements the hydrate method to modify the data before apply it to the
        the object
        """
        
        #Update the fabric
        if "fabric" in bundle.data and bundle.request.user.has_perm('acknowledgements.change_fabric'):
            try:
                fabric = Fabric.objects.get(pk=bundle.data["fabric"]["id"])
                bundle.obj.fabric = fabric
                logger.info("{0} changed fabric to {1}".format(bundle.obj.description,
                                                                fabric.description))
            except KeyError:
                raise ValueError("Missing fabric ID.")
            except Fabric.DoesNotExist:
                raise
        
        #Update the unit price
        if "unit_price" in bundle.data:
            if bundle.data["unit_price"] != bundle.obj.unit_price:
                if bundle.request.user.has_perm('acknowledgements.change_item_price'):
                    bundle.obj.unit_price = bundle.data['unit_price']
                    bundle.obj.total = bundle.obj.unit_price * bundle.obj.quantity
                else:
                    bundle.data['unit_price'] = bundle.obj.unit_price
                    
        return bundle

    def dehydrate(self, bundle):
        """
        Implment dehydration
        """
        
        #Add the acknowledgement ID
        bundle.data['acknowledgement'] = {'id': bundle.obj.acknowledgement.id}
        
        #Adds the fabric information if 
        #a fabric exists for this item
        if bundle.obj.fabric:
            bundle.data['fabric'] = {'id': bundle.obj.fabric.id,
                                'description': bundle.obj.fabric.description}
            #Attempts to add an url to the image if it exists
            try:
                bundle.data['fabric']['image'] = {'url': bundle.obj.fabric.image.generate_url()}
            except AttributeError:
                logger.info("Fabric {0} has no image.".format(bundle.obj.fabric.description))
                
        #Adds pillow dictionaries to the 'pillows'
        #category for every pillow referenced to the
        #item
        bundle.data['pillows'] = [{'id': pillow.id,
                                   'quantity': pillow.quantity,
                                   'type': pillow.type} for pillow
                                  in bundle.obj.pillow_set.all()]
        
        #Adds the image url to the outgoing data if it
        #exists
        if bundle.obj.image:
            bundle.data['image'] = {'url': bundle.obj.image.generate_url()}
            
        return bundle
        
