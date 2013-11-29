"""
API Resource classes for the
Purchase Order module
"""
import logging
import dateutil

from tastypie.resources import ModelResource
from tastypie import fields
from tastypie.authorization import DjangoAuthorization

from po.models import PurchaseOrder, Item
from contacts.models import Supplier


logger = logging.getLogger(__name__)


class PurchaseOrderResource(ModelResource):
    items = fields.ToManyField('po.api.ItemResource', 'items', related_name="purchase_order",
                               readonly=True, null=True, full=True)
    supplier = fields.ToOneField('contacts.api.SupplierResource', 'supplier',
                                 readonly=True, full=True)
    class Meta:
        resource_name = "purchase-order"
        queryset = PurchaseOrder.objects.all().order_by('-id')
        always_return_data = True
        authorization = DjangoAuthorization() 
        
    def hydrate(self, bundle):
        """
        Prepares the data before it is applied to the models
        """
        
        if bundle.obj.pk:
            try:
                #Updates the status of the items in the order
                for item in bundle.data['items']:
                    po_item = Item.objects.get(pk=item['id'])
                    po_item.status = item['status']
                    po_item.save()
            except:
                pass
            
        return bundle
    
    def dehydrate(self, bundle):
        """
        Get a single obj
        """
        #Add URLS for the acknowledgement
        #and the production pdf to the data
        #bundle
        if bundle.request.GET.get('pdf'):
            try:
                bundle.data['pdf'] = {'url': bundle.obj.pdf.generate_url()}
            except AttributeError: 
                logger.warn('Missing pdf')
            
        return bundle
        
    def obj_create(self, bundle, **kwargs):
        """
        Creates a new purchase order
        """
        logger.info("Creating a purchase order")
        #Create the object
        bundle.obj = PurchaseOrder()
        #Hydreate the obj
        bundle = self.full_hydrate(bundle, **kwargs)
        #Assign the employee
        bundle.obj.employee = bundle.request.user
        #Assign the supplier
        #and the terms
        try:
            bundle.obj.supplier = Supplier.objects.get(pk=bundle.data['supplier']['id'])
            bundle.obj.terms = bundle.obj.supplier.terms
            bundle.obj.currency = bundle.obj.supplier.currency
            bundle.obj.discount = bundle.obj.supplier.discount
        except KeyError:
            logger.error("Missing supplier's ID")
            raise ValueError("Expecting the supplier's ID.")
        except Supplier.DoesNotExist:
            logger.error("The supplier ID#{0} no longer exists.".format(bundle.data["supplier"]["id"]))
            raise 
        #Create the items 
        self.items = [Item.create(**item_data) for item_data in bundle.data['items']]
       
        bundle = self.save(bundle)
        
        for item in self.items:
            item.purchase_order = bundle.obj
            item.save()
            
        logger.debug("Calculating totals...")
        bundle.obj.calculate_total()
        bundle.obj.save()
        
        #Create a pdf to be uploaded 
        #to the S3 service. Then generate 
        #a url for the data that will be returned to the customer
        logger.info("Creating pdf for purchase order #{0}".format(bundle.obj.id))
        bundle.obj.create_and_upload_pdf()
        bundle.data["pdf"] = {"url": bundle.obj.pdf.generate_url()}
        
        return bundle
    
    
        
class ItemResource(ModelResource):
    class Meta:
        resource_name = "purchase-order-item"
        queryset = Item.objects.all()
        always_return_data = True
        authorization = DjangoAuthorization()
        allowed_methods = ['get', 'put', 'patch']
        
    def dehydrate(self, bundle):
        """
        Prepare data before it is returned to the client
        """
        bundle.data['units'] = bundle.obj.supply.units
        
        return bundle
        