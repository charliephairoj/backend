#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import dateutil.parser
import math
import logging
from decimal import *
import httplib2

from pytz import timezone
from datetime import datetime
from django.conf import settings
from django.db import models
from administrator.models import User, Storage, Company
from boto.s3.connection import S3Connection
from boto.s3.key import Key
import boto.ses
#from oauth2client.contrib.django_orm import Storage
from oauth2client.contrib import gce
from apiclient import discovery

from contacts.models import Customer
from products.models import Product, Upholstery
from projects.models import Project, Room, Phase
from supplies.models import Fabric
from acknowledgements.PDF import AcknowledgementPDF, ConfirmationPDF, ProductionPDF, ShippingLabelPDF, QualityControlPDF
from media.models import Log, S3Object
from administrator.models import CredentialsModel, Log as BaseLog
from trcloud.models import TRSalesOrder, TRContact


logger = logging.getLogger(__name__)


class Acknowledgement(models.Model):
    # Internal Attributes
    trcloud_id = models.IntegerField(null=True, default=0)
    trcloud_document_number = models.TextField(null=True, default="")
    po_id = models.TextField(default=None, null=True)
    
    time_created = models.DateTimeField(auto_now_add=True)
    _delivery_date = models.DateTimeField(db_column='delivery_date', null=True)
    status = models.TextField(db_column='status', default='acknowledged')
    remarks = models.TextField(null=True, default=None, blank=True)
    fob = models.TextField(null=True, blank=True)
    shipping_method = models.TextField(null=True, blank=True)
    
    last_modified = models.DateTimeField(auto_now=True)
    deleted = models.BooleanField(default=False)
    
    calendar_event_id = models.TextField(null=True)

    # Business Related Attributes
    document_number = models.IntegerField(default=0)
    company_name = models.TextField(default="Alinea Group Co., Ltd.")
    customer_name = models.TextField()


    # Relationships
    company = models.ForeignKey(Company, related_name='acknowledgements', on_delete=models.CASCADE)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='acknowledgements')
    employee = models.ForeignKey(User, db_column='employee_id', on_delete=models.PROTECT)
    project = models.ForeignKey(Project, null=True, blank=True, related_name='acknowledgements', on_delete=models.PROTECT)
    room = models.ForeignKey(Room, null=True, blank=True, related_name='acknowledgements', on_delete=models.PROTECT)
    phase = models.ForeignKey(Phase, null=True, blank=True, related_name='acknowledgements', on_delete=models.PROTECT)
    acknowledgement_pdf = models.ForeignKey(S3Object,
                                            null=True,
                                            related_name='+',
                                            db_column="acknowledgement_pdf")
    confirmation_pdf = models.ForeignKey(S3Object, 
                                        null=True, 
                                        related_name="+", 
                                        db_column="confirmation_pdf")
    production_pdf = models.ForeignKey(S3Object,
                                       null=True,
                                       related_name='+',
                                       db_column="production_pdf")
    label_pdf = models.ForeignKey(S3Object,
                                       null=True,
                                       related_name='+',
                                       db_column="label_pdf")
    original_acknowledgement_pdf = models.ForeignKey(S3Object,
                                                     null=True,
                                                     related_name='+',
                                                     db_column="original_acknowledgement_pdf")
    files = models.ManyToManyField(S3Object, through="File", related_name="acknowledgement")

    # VATs
    vat = models.IntegerField(default=0)
    vat_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)

    #Discounts
    discount = models.IntegerField(default=0)
    second_discount = models.IntegerField(default=0)
    discount_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    second_discount_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)

    # Totals
    # Totals of item totals
    subtotal = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    # Total after first discount
    post_discount_total = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    # Total after second Discount
    total = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    # Total after all discounts and Vats
    grand_total = models.DecimalField(max_digits=15, decimal_places=2, default=0)

    # None Database attributes
    current_user = None 
    calendar_service = None

    @property
    def delivery_date(self):
        return self._delivery_date
        
    @delivery_date.setter
    def delivery_date(self, value):
        self._delivery_date = value
        
    # @property
    # def status(self):
    #     return self._status

    # @status.setter
    # def status(self, value):
    #     self._status = value

    @property
    def balance(self):
        return self.grand_total - sum([inv.grand_total for inv in self.invoices.all()])
        
    @classmethod
    def create(cls, user, **kwargs):
        """Creates the acknowledgement

        This method accept data to set and then creates
        an accompanying PDF and logs the event. A User
        Object is required to authorize certain data
        """
        acknowledgement = cls()

        # Get Customer and create in TRCloud if necessary
        acknowledgement.customer = Customer.objects.get(id=kwargs['customer']['id'])
        try:
            if not acknowledgement.customer.trcloud_id == 0:
                acknowledgement.customer.create_in_trcloud()
        except Exception as e:
            logger.warn(e)

        acknowledgement.employee = user

        acknowledgement.delivery_date = dateutil.parser.parse(kwargs['delivery_date'])
        acknowledgement.status = 'ACKNOWLEDGED'
        try:
            acknowledgement.vat = int(kwargs["vat"])
        except KeyError:
            acknowledgement.vat = 0
        try:
            acknowledgement.po_id = kwargs["po_id"]
        except KeyError:
            raise AttributeError("Missing Purchase Order number.")
        try:
            acknowledgement.remarks = kwargs["remarks"]
        except KeyError:
            pass
        #Create the products without saving
        acknowledgement.items = [Item.create(acknowledgement=acknowledgement,
                                             commit=False,
                                             **product_data) for product_data in kwargs['products']]

        acknowledgement.calculate_totals(acknowledgement.items)
        
        #Save the ack and by overriden method, the items
        acknowledgement.save()

        #Create the order PDFs
        ack, production = acknowledgement._create_pdfs()
        ack_key = "acknowledgement/Acknowledgement-{0}.pdf".format(acknowledgement.document_number)
        production_key = "acknowledgement/Production-{0}.pdf".format(acknowledgement.document_number)
        bucket = "document.dellarobbiathailand.com"
        ack_pdf = S3Object.create(ack, ack_key, bucket, encrypt_key=True)
        prod_pdf = S3Object.create(production, production_key, bucket, encrypt_key=True)
        acknowledgement.acknowledgement_pdf = ack_pdf
        acknowledgement.production_pdf = prod_pdf
        acknowledgement.original_acknowledgement_pdf = ack_pdf

        #Save Ack with pdf data
        acknowledgement.save()

        return acknowledgement
        
    def save(self, *args, **kwargs):

        if self.document_number == 0 or self.document_number is None:
            try:
                last_id = Acknowledgement.objects.filter(company=self.company).latest('document_number').document_number + 1
            except Acknowledgement.DoesNotExist:
                last_id = 100001

            self.document_number = last_id

        super(Acknowledgement, self).save(*args, **kwargs)

    def delete(self):
        """
        Overrides the standard delete method.
        
        This method will simply make the acknowledgement as deleted in
        the database rather an actually delete the record
        """
        self.deleted = True

    def filtered_logs(self):
        """Filter logs source"""
        return self.logs.exclude(type__icontains="error")

    def update(self, data=None, employee=None):
        """"Updates the acknowledgement

        Updates the acknowledgement with the new data
        and creates a new pdf for acknowledgement and production
        """
        self.current_employee = employee
        try:
            self.delivery_date = data["delivery_date"]
            self.save()
        except:
            pass

        self.calculate_totals()

        ack_filename, production_filename = self.create_pdfs()
        ack_key = "acknowledgement/Acknowledgement-{0}-revision.pdf".format(self.document_number)
        production_key = "acknowledgement/Production-{0}-revision.pdf".format(self.document_number)
        bucket = "document.dellarobbiathailand.com"
        ack_pdf = S3Object.create(ack_filename, ack_key, bucket)
        prod_pdf = S3Object.create(production_filename, production_key, bucket)

        self.acknowledgement_pdf = ack_pdf
        self.production_pdf = prod_pdf

        self.save()

    def create_in_trcloud(self):
        """Create a Sales Order in TRCloud"""

        # Create customer if does not already exist
        if not self.customer.trcloud_id:

            # Search current clients to double check if 
            contacts = TRContact.search(self.customer.name)

            if len(contacts) == 0:
                try:

                    self.customer.contact_type = "normal"
                    self.customer.create_in_trcloud()
                except Exception as e:
                    message = "Unable to create contact in TRCloud"
                    Log.objects.create(message=message,
                                       type="TRCLOUD",
                                       user=self.employee)
            else:  
                self.customer.trcloud_id = contacts[0]['contact_id']
                self.customer.tax_id = contacts[0]['tax_id']
                self.customer.save()

        tr_so = TRSalesOrder()

        tr_so = self._populate_for_trcloud(tr_so)
        
        try:
            tr_so.create()
        except Exception as e:
            message = "Unable to create Sales Order for acknowledgement {0} in TRCloud because: {1}"
            message = message.format(self.document_number, e)
            Log.objects.create(message=message,
                                       type="TRCLOUD",
                                       user=self.employee)
                                       
        self.trcloud_id = tr_so.id
        self.trcloud_document_number = tr_so.document_number
        self.save()

        # Set the trcloud_id for items
        for product in tr_so.products:
            try:
                item = self.items.get(description=product['product'],
                                      quantity=product['quantity'])
            except Item.DoesNotExist as e:
                logger.debug(product['product'])
                logger.debug(product['quantity'])

            logger.debug(product)
            logger.debug(item.__dict__)
            item.trcloud_id = product['id']

    def update_in_trcloud(self):
        """Create a Sales Order in TRCloud"""
        tr_so = TRSalesOrder()

        tr_so = self._populate_for_trcloud(tr_so)
        tr_so.document_number = self.trcloud_document_number
        tr_so.id = self.trcloud_id

        try:
            tr_so.update()
        except Exception as e:
            message = "Unable to update Sales Order for acknowledgement {0} in TRCloud because: {1}"
            message = message.format(self.document_number, e)
            Log.objects.create(message=message,
                                       type="TRCLOUD",
                                       user=self.employee)
       

        self.save()
        
    def ship(self, delivery_date, employee):
        """Changes status to 'SHIPPED'

        Change the order status to ship and logs who ships it
        """
        try:
            message = "Ack# {0} shipped on {1}".format(self.document_number, delivery_date.strftime('%B %d, %Y'))
        except AttributeError:
            raise TypeError("Missing Delivery Date")
    
    def create_and_upload_pdfs(self, delete_original=True):
        ack_filename, production_filename, label_filename, qc_filename = self.create_pdfs()
        ack_key = "acknowledgement/{0}/Acknowledgement-{0}.pdf".format(self.document_number)
        #confirmation_key = "acknowledgement/{0}/Confirmation-{0}.pdf".format(self.document_number)
        production_key = "acknowledgement/{0}/Production-{0}.pdf".format(self.document_number)
        label_key = "acknowledgement/{0}/Label-{0}.pdf".format(self.document_number)
        bucket = "document.dellarobbiathailand.com"
        ack_pdf = S3Object.create(ack_filename, ack_key, bucket, delete_original=delete_original)
        #confirmation_pdf = S3Object.create(confirmation_filename, confirmation_key, bucket, delete_original=delete_original)
        prod_pdf = S3Object.create(production_filename, production_key, bucket, delete_original=delete_original)
        label_pdf = S3Object.create(label_filename, label_key, bucket, delete_original=delete_original)

        # Create QC key and upload and add to files
        try:
            qc_key = "acknowledgment/{0}/Quality_Control-{0}.pdf".format(self.document_number)
            qc_pdf = S3Object.create(qc_filename, qc_key, bucket, delete_original=delete_original)

            # Add qc file to the
            File.objects.create(file=qc_pdf, acknowledgement=self)
        except Exception as e:
            logger.warn(e)

        # Save references for files
        self.label_pdf = label_pdf
        self.acknowledgement_pdf = ack_pdf
        #self.confirmation_pdf = confirmation_pdf
        self.production_pdf = prod_pdf

        
        
        self.save()
        
    def create_pdfs(self):
        """Creates Production and Acknowledgement PDFs

        This method will extract the necessary data to 
        create the pdfs from the object itself. It requires
        no arguments
        """
        products = self.items.all().order_by('id')

        # Initialize pdfs
        ack_pdf = AcknowledgementPDF(customer=self.customer, ack=self, products=products)
        confirmation_pdf = ConfirmationPDF(customer=self.customer, ack=self, products=products)
        production_pdf = ProductionPDF(customer=self.customer, ack=self, products=products)
        label_pdf = ShippingLabelPDF(customer=self.customer, ack=self, products=products)

        # Create pdfs
        ack_filename = ack_pdf.create()
        #confirmation_filename = confirmation_pdf.create()
        production_filename = production_pdf.create()
        
        label_filename = label_pdf.create()

        # Initialize and create PDF section
        try:
            qc_pdf = QualityControlPDF(customer=self.customer, ack=self, products=products)
            qc_filename = qc_pdf.create()
        except Exception as e:
            logger.warn(e)
            qc_filename = ""

        return ack_filename, production_filename, label_filename, qc_filename

    def create_and_upload_checklist(self):
        """
        Creates a shipping Label pdf and uploads to S3 service
        """
        products = self.items.all().order_by('id')
        qc_pdf = QualityControlPDF(customer=self.customer, ack=self, products=products)
        qc_filename = qc_pdf.create()
        label_key = "acknowledgement/{0}/Quality_Control-{0}.pdf".format(self.document_number)
        bucket = "document.dellarobbiathailand.com"
        #qc_pdf = S3Object.create(qc_filename, label_key, bucket, delete_original=False)

        #logger.debug(qc_pdf.generate_url())

        self.save()

    def create_and_upload_shipping_label(self):
        """
        Creates a shipping Label pdf and uploads to S3 service
        """
        products = self.items.all().order_by('id')
        label_pdf = ShippingLabelPDF(customer=self.customer, ack=self, products=products)
        label_filename = label_pdf.create()
        label_key = "acknowledgement/Label-{0}.pdf".format(self.document_number)
        bucket = "document.dellarobbiathailand.com"
        label_pdf = S3Object.create(label_filename, label_key, bucket)

        self.label_pdf = label_pdf
        self.save()
        
    def calculate_totals(self, items=None):
        #Define items if not already defined
        if not items:
            items = self.items.exclude(deleted=True)

        totals = self._calculate_totals(items)

        # Totals
        self.subtotal = totals['subtotal']
        self.post_discount_total = totals['post_discount_total']
        self.total = totals['total']
        self.grand_total = totals['grand_total']

        # VAT
        self.vat_amount = totals['vat_amount']
        self.second_discount_amount = totals['second_discount_amount']

        # Discounts
        self.discount_amount = totals['discount_amount']
        self.second_discount_amount = totals['second_discount_amount']

        self.save()

    def _calculate_totals(self, items=None):
        """Calculates the total of the order

        Uses the items argument to calculate the cost
        of the project. If the argument is null then the
        items are pulled from the database relationship.
        We use the argument first in the case of where
        we are creating a new Acknowledgement, and the
        items and acknowledgement have not yet been saved
        """
        # Totals
        # Total of items totals
        subtotal = 0
        # Total after discount        
        post_discount_total = 0
        # Total after second discount
        total = 0
        # Total after Vat
        grand_total = 0

        # Running total to check
        running_total = 0

        # Discount amounts
        # First Discount
        discount_amount = 0
        # Second Amount
        second_discount_amount = 0

        # Calculations
        # Calculate the subtotal
        for product in items:
            logger.debug("item: {0:.2f} x {1} = {2:.2f}".format(product.unit_price, product.quantity, product.total))
            subtotal += product.total

        # Set running_total to subtotal
        running_total += subtotal
            
        # Set the subtotal
        logger.debug("subtotal: = {0:.2f}".format(running_total))
        
        if subtotal == 0:
            return {
                'subtotal': 0,
                'post_discount_total': 0,
                'total': 0,
                'grand_total': 0,
                'vat_amount': 0,
                'discount_amount': 0,
                'second_discount_amount': 0
            }


        # Calculate discount
        discount_amount = (Decimal(self.discount) / 100) * subtotal
        logger.debug("discount {0}%: - {1:.2f}".format(self.discount, discount_amount))

        # Assert Discount amount is proportional to subtotal percent
        assert (discount_amount / subtotal) == Decimal(self.discount) / 100, "{0}: {1}".format((discount_amount / subtotal), Decimal(self.discount) / 100)

        # Apply discount
        post_discount_total = subtotal - discount_amount
        running_total -= discount_amount

        # Assert Discounted amount is proportional to discount and subtotal
        assert post_discount_total == running_total
        assert (post_discount_total / subtotal) == ((100 - Decimal(self.discount)) / 100)

        # Calculate a second discount
        second_discount_amount = (Decimal(self.second_discount) / 100) * post_discount_total
        logger.debug("second discount {0}%: - {1:.2f}".format(self.second_discount, second_discount_amount))
        
        # Assert second discount amount is proportional to total percent
        assert (second_discount_amount / post_discount_total) == Decimal(self.second_discount) / 100
        # Assert second discount amount is not proportional to total percent
        if self.second_discount > 0:
            assert (second_discount_amount / subtotal) != Decimal(self.second_discount) / 100

        # Apply second discount
        total = post_discount_total - second_discount_amount
        running_total -= second_discount_amount
        logger.debug("total: = {0:.2f}".format(total))

        # Assert total is proportional to subtotal
        assert total == running_total
        tpart1 = (total / subtotal)
        tpart2 = 1 - (Decimal(self.discount) / 100) 
        tpart2 = tpart2 - ((Decimal(self.discount) / 100) * (Decimal(self.second_discount) / 100))
        assert tpart2 > 0 and tpart2 <= 1
        assert tpart1 == tpart2, "{0}: {1}".format(tpart1, tpart2)
        if self.second_discount > 0:
            t2part1 = (total / subtotal)
            t2part2 = 1 - (Decimal(self.discount) / 100) 
            t2part2 = tpart2 - (Decimal(self.second_discount) / 100)
            assert t2part2 > 0 and t2part2 <= 1
            assert t2part1 != t2part2

        
        #Calculate VAT
        vat_amount = (Decimal(self.vat) / 100) * total
        logger.debug("vat: + {0:.2f}".format(vat_amount))

        # Assert VAT
        assert (vat_amount / total) == (Decimal(self.vat) / 100)

        # Apply VAT
        grand_total = total + vat_amount
        running_total += vat_amount
        logger.debug("grand total: = {0:.2f}".format(grand_total))

        # Assert second discounted amount is proportional to discount and total
        assert grand_total == running_total
        assert (grand_total / total) == Decimal('1') + (Decimal(self.vat) / 100)
        assert grand_total == (subtotal - discount_amount - second_discount_amount + vat_amount)

        return {
            'subtotal': subtotal,
            'post_discount_total': post_discount_total,
            'total': total,
            'grand_total': grand_total,
            'vat_amount': vat_amount,
            'discount_amount': discount_amount,
            'second_discount_amount': second_discount_amount
        }

    def _populate_for_trcloud(self, tr_so):

        # Add customer to data package
        tr_so.customer['contact_id'] = self.customer.trcloud_id
        tr_so.customer['name'] = self.customer.name
        # Set Orgnization name 
        if u"co.," or u"บริษัท" in self.name.lower():
            tr_so.customer['organization'] = self.customer.name
        
        tr_so.customer['branch'] = u"สำนักงานใหญ่"
        tr_so.customer['email'] = self.customer.email
        tr_so.customer['telephone'] = self.customer.telephone

        #Set Address
        try:
            address = self.customer.addresses.all()[0]
            tr_address = u"{0}, {1}, {2}, {3} {4}".format(address.address1,
                                                        address.city or "",
                                                        address.territory or "",
                                                        address.country or "",
                                                        address.zipcode or "")
            tr_so.customer['address'] = tr_address
        except IndexError as e:
            tr_so.customer['address'] = ''
            
        tr_so.customer['tax_id'] = self.customer.tax_id or ""

        # Set Date
        d = datetime.now()
        tr_so.document_number = self.trcloud_document_number
        tr_so.issue_date = self.time_created.strftime("%Y-%m-%d")
        tr_so.delivery_due = self.delivery_date.strftime("%Y-%m-%d")
        tr_so.company_format = "SO"
        tr_so.tax = "{0:.2f}".format((Decimal(str(self.vat))/Decimal('100')) * self.subtotal)
        tr_so.total = float(self.subtotal)
        tr_so.grand_total = float(self.total)
        tr_so.customer_id = self.customer.trcloud_id

        # Add Products
        for item in self.items.all():
            tr_so.products.append({'id': item.id,
                                   'product': item.description or '',
                                   'price': "{0:.2f}".format(item.unit_price or 0),
                                   'quantity': "{0:.2f}".format(item.quantity or 0),
                                   'before': "{0:.2f}".format(item.total or 0),
                                   'amount': "{0:.2f}".format((item.total * Decimal('1.07')) or 0),
                                   'vat':'7%'})
        
        return tr_so

    def _change_fabric(self, product, fabric, employee=None):
        """Changes the fabric for a product

        Requires the product, the fabric and the employee performing
        the change. The event is logged using the provided employee
        """
        try:
            message = "Changed fabric from {0} to {1}".format(product.fabric.description, fabric.description)
        except:
            message = "Changed fabric to {0}".format(fabric.description)
        self._create_log(message, employee)
        product.fabric = fabric
        product.save()

    def _email(self, pdf, recipients):
        """Emails an order confirmation"""
        conn = boto.ses.connect_to_region('us-east-1')
        body = u"""<table width="500" cellpadding="3" cellspacing="0">
                      <tr>
                          <td style="border-bottom-width:1px; border-bottom-style:solid; border-bottom-color:#777" width="70%"> 
                              <a href="http://www.dellarobbiathailand.com"><img height="30px" src="https://s3-ap-southeast-1.amazonaws.com/media.dellarobbiathailand.com/DRLogo.jpg"></a> 
                          </td>
                          <td style="border-bottom-width:1px; border-bottom-style:solid; border-bottom-color:#777; color:#777; font-size:14px" width="30%" align="right" valign="bottom">Order Received</td> 
                      </tr>
                      <tr>
                          <td width="500" colspan="2">
                          <br />
                          <br />
                          <p> Dear {customer},
                          <br />
                          <br /> Thank you for placing an order with us. Here are the details of your order, for your conveniece: 
                          <br />
                          <br />
                          <table cellpadding="3" cellspacing="0" width="500">
                              <tr>
                                  <td align="left"> <b style="color:#000">Order Number:</b></td>
                                  <td align="right"> <b>{id}</b> </td>
                              </tr>
                              <tr>
                                  <td align="left">
                                      <b style="color:#000">Acknowledgement:</b>
                                  </td>
                                  <td align="right">
                                      <a href="{src}">View Your Acknowledgement(Link Valid for 72 Hours)</a>
                                  </td>
                              </tr>
                              <tr>
                                  <td align="left"> <b style="color:#000">Estimated Delivery Date:</b>
                                  </td>
                                  <td align="right"> <b>{delivery_date}</b>
                                  </td>
                              </tr>
                          </table>
                          <br />
                          <br />
                          If you have any questions, comments or concerns, please don\'t hesistate to
                          <a href="info@dellarobbiathailand.com">contact us</a>.
                          <br />
                          <br /> Sincerely,
                          <br />The Dellarobbia Customer Service Team
                      </p>
                  </td>
              </tr>
          </table>""".format(id=self.document_number, customer=self.customer.name,
                             src=pdf.generate_url(),
                             delivery_date=self.delivery_date.strftime('%B %d, %Y'))

        conn.send_email('no-replay@dellarobbiathailand.com',
                        'Acknowledgement of Order Placed',
                        body,
                        recipients,
                        format='html')
    
    def _get_calendar_service(self, user):
        if self.calendar_service:
            self.calendar_service
        else:
            
            storage = Storage(CredentialsModel, 'id', user, 'credential')
            credentials = storage.get()
        
            http = credentials.authorize(httplib2.Http())
            self.calendar_service = discovery.build('calendar', 'v3', http=http)
            
        return self.calendar_service
        
    def _get_calendar(self, user):
        service = self._get_calendar_service(user)
        response = service.calendarList().list().execute()
        
        calendar_summaries = [cal['summary'].lower() for cal in response['items']]
    
        # Check if user does not already has account payables
        if 'deliveries' not in calendar_summaries:
            # Get calendar
            cal_id = 'dellarobbiathailand.com_vl7drjcuulloicm0qlupgsr4ko@group.calendar.google.com'
            calendar = service.calendars().get(calendarId=cal_id).execute()
     
            # Add calendar to user's calendarList
            service.calendarList().insert(body={
                'id': calendar['id']
            }).execute()
            
        else:
            # Get calendar is already in calendarList
            for cal in response['items']:
                if cal['summary'].lower() == 'deliveries':
                    calendar = cal
            
        return calendar
        
    def create_calendar_event(self, user):
        """Create a calendar event for the expected delivery date
        
        """
        service = self._get_calendar_service(user)
        calendar = self._get_calendar(user)
        
        response = service.events().insert(calendarId=calendar['id'], 
                                           body=self._get_event_body()).execute()
        self.calendar_event_id = response['id']
        self.save()
        
    def update_calendar_event(self, user=None):
        """Create a calendar event for the expected delivery date
        
        """
        if user is None:
            user = self.current_user or self.employee
        
        if self.calendar_event_id:
            
            service = self._get_calendar_service(user)
            calendar = self._get_calendar(user)
        
            resp = service.events().update(calendarId=calendar['id'], 
                                           eventId=self.calendar_event_id, 
                                           body=self._get_event_body()).execute()
                                          
        else:
            
            self.create_calendar_event(user)
                                                                       
    def _get_event_body(self):
        evt = {
            'summary': "Ack {0}".format(self.document_number),
            'location': self._get_address_as_string(),
            'description': self._get_description_as_string(),
            'start': {
                'date': self.delivery_date.strftime('%Y-%m-%d')
            },
            'end': {
                'date': self.delivery_date.strftime('%Y-%m-%d')
            },
            'reminders': {
                'useDefault': False,
                'overrides': [
                  {'method': 'email', 'minutes': 24 * 60 * 2},
                  {'method': 'email', 'minutes': 120},
                ]
            }
        }
        
        return evt

    def _get_address_as_string(self):
        try:
            addr_str = ""
            addr = self.customer.addresses.all()[0]
        
            addr_str += addr.address1 + ", " + addr.city + ", " + addr.territory
            addr_str += ", " + addr.country + " " + addr.zipcode
        
            return addr_str
        except Exception as e:
            logger.warn(e)
            return ""
        
    def _get_description_as_string(self):
        description = u"""
        Acknowledgement: {0}
        Customer: {1}
        Qty     Items: 
        """.format(self.document_number, self.customer.name)
        
        for i in self.items.all().order_by('id'):
            description += u"{0:.2f}  {1}".format(i.quantity, i.description)
            
        return description
        
    def __str__(self):
        return u"Acknowledgement #{0}".format(self.document_number)
        

class File(models.Model):
    acknowledgement = models.ForeignKey(Acknowledgement, on_delete=models.CASCADE)
    file = models.ForeignKey(S3Object, related_name='acknowledgement_files', on_delete=models.CASCADE)
    
    
class Item(models.Model):
    trcloud_id = models.IntegerField(null=True, blank=True)
    acknowledgement = models.ForeignKey(Acknowledgement, related_name="items", on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    type = models.TextField(null=True, blank=True)
    quantity = models.DecimalField(max_digits=15, decimal_places=2, null=False)
    unit_price = models.DecimalField(null=True, max_digits=15, decimal_places=2)
    total = models.DecimalField(null=True, max_digits=15, decimal_places=2)
    width = models.IntegerField(db_column='width', default=0)
    depth = models.IntegerField(db_column='depth', default=0)
    height = models.IntegerField(db_column='height', default=0)
    units = models.CharField(max_length=20, default='mm', blank=True)
    fabric = models.ForeignKey(Fabric, null=True, blank=True, on_delete=models.PROTECT)
    fabric_quantity = models.DecimalField(null=True, max_digits=12, decimal_places=2)
    description = models.TextField()
    is_custom_size = models.BooleanField(db_column='is_custom_size', default=False)
    is_custom_item = models.BooleanField(default=False)
    status = models.CharField(db_column="status", max_length=50, default="acknowledged")
    comments = models.TextField(null=True, blank=True)
    location = models.TextField(null=True, blank=True)
    image = models.ForeignKey(S3Object, null=True, blank=True, on_delete=models.PROTECT)
    deleted = models.BooleanField(default=False)
    inventory = models.BooleanField(default=False)
    last_modified = models.DateTimeField(auto_now=True)

    class Meta:
        permissions = (('change_item_price', 'Can edit item price'),
                       ('change_fabric', "Can change fabric"))

    @classmethod
    def create(cls, acknowledgement=None, commit=True, **kwargs):
        """Creates an Item"""
        item = cls()
        item.acknowledgement = acknowledgement
        try:
            item.product = Product.objects.get(id=kwargs["id"])
            logger.info(u"Item set to {0}...".format(item.product.description))
        except KeyError:
            try:
                item.product = Product.objects.get(id=kwargs["product"]["id"])
            except KeyError:
                item.product = Product.objects.get(id=10436)
        except Product.DoesNotExist:
            item.product = Product.objects.get(id=10436)
            
        item.status = "ACKNOWLEDGED"

        try:
            item.quantity = int(kwargs["quantity"])
        except KeyError:
            raise AttributeError("Missing Quantity.")

        item._apply_product_data()
        item._apply_data(**kwargs)

        #Save the item if commit is true
        if commit:
            item.save()

        return item

    def _apply_product_data(self):
        """Applies data from the set product

        Requires no arguments. The data is extracted
        from the product referenced by the item
        """
        
        self.description = self.product.description
        
        """
        This section has been deprecated as we are now moving
        to a single price system
        
        #Determines the unit price of the
        #the item based on the type of 
        #customer. And then calculates the
        #total price based on quantity
        if self.acknowledgement.customer.type == "Retail":
            self.unit_price = self.product.retail_price
        elif self.acknowledgement.customer.type == "Dealer":
            self.unit_price = self.product.wholesale_price
        else:
            self.unit_price = self.product.retail_price
        """
        self.unit_price = self.product.price
        logger.info(u"Item unit price set to {0:.2f}...".format(self.unit_price))

        #Calculate the total cost of the the item
        self.total = self.unit_price * Decimal(self.quantity)
        logger.info(u"Item total price set to {0:.2f}...".format(self.total))

        #Set the appropriate dimensions or to 0
        #if no dimensions are available from the model
        logger.info(u"Setting standard dimensions from standard product...")
        self.width = self.product.width if self.product.width else 0
        self.depth = self.product.depth if self.product.depth else 0
        self.height = self.product.height if self.product.height else 0

        self.image = self.product.image
        

    def _apply_data(self, **kwargs):
        """Applies data to the attributes

        Requires a User to authenticate what can and
        cannot be applied"""
        if "status" in kwargs:
            self.status = kwargs["status"]
            if self.status.lower() == "inventory":
                self.inventory = True
        if "comments" in kwargs:
            self.comments = kwargs["comments"]
        if "description" in kwargs:
            self.description = kwargs['description']
        #Set the size of item if custom
        if "is_custom_size" in kwargs:
            if kwargs["is_custom_size"] == True:
                self.is_custom_size = True
                try:
                    self.width = int(kwargs['width'])
                except (ValueError, KeyError, TypeError):
                    pass
                try:
                    self.depth = int(kwargs['depth'])
                except (ValueError, KeyError, TypeError):
                    pass
                try:
                    self.height = int(kwargs['height'])
                except (ValueError, KeyError, TypeError):
                    pass

        #Calculate the price of the item
        if "custom_price" in kwargs:
            try:
                if float(kwargs['custom_price']) > 0:
                    self.unit_price = Decimal(kwargs["custom_price"])
                    self.total = self.unit_price * Decimal(str(self.quantity))
                else:
                    self._calculate_custom_price()
            except: 
                self._calculate_custom_price()
        else:
            self._calculate_custom_price()

        #Create a Item from a custom product
        if "is_custom" in kwargs:
            if kwargs["is_custom"] == True:
                self.is_custom_item = True
                self.description = kwargs["description"]
                if "image" in kwargs:
                    self.image = S3Object.objects.get(pk=kwargs["image"]["id"])
                
                if self.description.strip() == "Custom Custom":
                    logger.error(u"Custom Item Description is still wrong")
        #Sets the fabric for the item
        if "fabric" in kwargs:
            try:
                self.fabric = Fabric.objects.get(pk=kwargs["fabric"]["id"])
                logger.info(u"{0} fabric set to {1} \n".format(self.description,
                                                           self.fabric.description))
            except Fabric.DoesNotExist as e:
                logger.debug(u"Error: {0} /Fabric: {1}".format(e, kwargs["fabric"]["id"]))

        #Sets all the pillows and the fabrics
        #for the item
        if "pillows" in kwargs:
            pillows = self._condense_pillows(kwargs["pillows"])
            self.pillows = [self._create_pillow(keys[0],
                                                pillows[keys],
                                                keys[1]) for keys in pillows]

    def _calculate_custom_price(self):
        """
        Caluates the custom price based on dimensions.
        
        Dellarobbia Collection:
        Charge 10% for first 15cm change, then adds 1% for each extra 5cm for all dimensions summatively
        
        Dwell Living:
        Charge 5% for first 15cm change, then adds 1% for each extra 5cm for all dimensions summatively
        """
        logger.info(u"Calculating custom price for {0}...".format(self.description))
        dimensions = {}
        try:
            dimensions['width_difference'] = self.width - self.product.width
        except:
            dimensions['width_difference'] = 0
        try:
            dimensions['depth_difference'] = self.depth - self.product.depth
        except:
            dimensions['depth_difference'] = 0
        try:
            dimensions['height_difference'] = self.height - self.product.height
        except:
            dimensions['height_difference'] = 0

        if self.product.collection == "Dellarobbia Thailand":
            upcharge_percentage = sum(self._calculate_upcharge(dimensions[key], 150, 10, 1) for key in dimensions)
        elif self.product.collection == "Dwell Living":
            upcharge_percentage = sum(self._calculate_upcharge(dimensions[key], 150, 10, 1) for key in dimensions)
        else:
            upcharge_percentage = 0

        self.unit_price = self.unit_price + (self.unit_price * (Decimal(upcharge_percentage) / 100))
        logger.info(u"Setting unit price of {0} to {1:.2f}".format(self.description, 
                                                              self.unit_price))
        
        self.total = self.unit_price * self.quantity
        logger.info(u"Setting total of {0} to {1:.2f}...".format(self.description,
                                                            self.total))

    def _calculate_upcharge(self, difference, boundary, initial, increment):
        """Returns the correct upcharge percentage as a whole number

        >>>self._calculate_upcharge(100, 150, 10, 1)
        10
        """
        if difference > 0:
            upcharge_percentage = initial + sum(increment for i in xrange(int(math.ceil(float(difference - boundary) / 50))))
            return upcharge_percentage
        else:
            return 0

    def _condense_pillows(self, pillows_data):
        """Removes the duplicate pillows from the data and condenses it.

        Duplicates pillows are added together and the duplicates are removed
        with the presence reflected in the quantity of a single pillow
        """

        pillows = {}
        for pillow in pillows_data:
            try:
                pillows[(pillow["type"], pillow["fabric"]["id"])] += int(1)
            except KeyError:
                try:
                    pillows[(pillow["type"], pillow["fabric"]["id"])] = int(1)
                except KeyError:
                    try:
                        pillows[(pillow["type"], None)] += int(1)
                    except KeyError:
                        pillows[(pillow["type"], None)] = int(1)
        return pillows

    def _create_pillow(self, type, quantity, fabric_id=None):
        """
        Creates and returns a pillow

        This method will create a pillow. If there is a corresponding fabric
        it is added to the pillow, if not then the pillow is returned without one
        """
        try:
            return Pillow(item=self,
                          type=type,
                          quantity=quantity,
                          fabric=Fabric.objects.get(pk=fabric_id))
        except Fabric.DoesNotExist:
            return Pillow(item=self,
                          type=type,
                          quantity=quantity)

    def _get_image_url(self):
        """Gets the item's default image."""
        try:
            conn = S3Connection()
            url = conn.generate_url(1800, 'GET', bucket=self.bucket,
                                    key=self.image_key, force_http=True)
            return url
        except Exception:
            return None


class Pillow(models.Model):
    item = models.ForeignKey(Item, related_name='pillows', on_delete=models.CASCADE)
    type = models.CharField(db_column="type", max_length=10)
    quantity = models.IntegerField(default=1)
    fabric = models.ForeignKey(Fabric, null=True, blank=True, on_delete=models.PROTECT)
    fabric_quantity = models.DecimalField(null=True, max_digits=12, decimal_places=2)

    @classmethod
    def create(cls, **kwargs):
        """Creates a new pillow"""
        pillow = cls(**kwargs)
        pillow.save()
        return pillow


class Component(models.Model):
    item = models.ForeignKey(Item, related_name="components", on_delete=models.CASCADE)
    description = models.TextField()
    quantity = models.DecimalField(max_digits=15, decimal_places=2, null=False)


class Log(BaseLog):
    log_ptr = models.OneToOneField(BaseLog, related_name='+')
    acknowledgement = models.ForeignKey(Acknowledgement, related_name='logs', on_delete=models.PROTECT)

    @classmethod
    def create(cls, **kwargs):

        log_type = kwargs.pop('type', 'ACKNOWLEDGEMENT')

        log = cls(type=log_type, **kwargs)
        log.save()

        return log
    

class Delivery(models.Model):
    acknowledgement = models.ForeignKey(Acknowledgement, null=True)
    description = models.TextField()
    _delivery_date = models.DateTimeField()
    longitude = models.DecimalField(decimal_places=6, max_digits=9, null=True)
    latitude = models.DecimalField(decimal_places=6, max_digits=9, null=True)
    last_modified = models.DateTimeField(auto_now=True)

    @property
    def delivery_date(self):
        return self._delivery_date

    @delivery_date.setter
    def delivery_date(self, new_date):
        self._delivery_date = new_date

    @classmethod
    def create(cls, **kwargs):
        delivery = cls(**kwargs)
        try:
            delivery.description = kwargs["description"]
            delivery.delivery_date = kwargs["delivery_date"]
        except:
            raise Exception("Missing required information")

        try:
            delivery.latitude = kwargs["latitude"]
            delivery.longitude = kwargs["longitude"]
        except:
            pass

        try:
            delivery.acknowledgement = kwargs["acknowledgement"]
        except:
            pass

        delivery.save()
        return delivery

    def to_dict(self):
        return {'id': self.id,
                'description': self.description,
                'delivery_date': self.delivery_date.isoformat()}


