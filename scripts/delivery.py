"""
Retrieves a list of Orders and products to be shipped 
in the 14 day period starting today, and creates an 
html message. This email message is then sent to 
the email address
"""

import sys, os, django
sys.path.append('/Users/Charlie/Sites/employee/backend')
sys.path.append('/home/django_worker/backend')
os.environ['DJANGO_SETTINGS_MODULE'] = 'EmployeeCenter.settings'
from decimal import Decimal
from datetime import timedelta, datetime
import logging

from django.template.loader import render_to_string
from django.conf import settings
import boto.ses

from acknowledgements.models import Acknowledgement


django.setup()


class AcknowledgementEmail(object):
    queryset = Acknowledgement.objects.all()
    message = "<div style='font-family:Tahoma;font-size:3mm;color:#595959;width:190mm'>"
    status_width = "18mm"
    customer_width = "auto"
    cell_style = """
                 border-bottom:1px solid #595959;
                 border-right:1px solid #595959;
                 padding:1em 0.5em;
                 text-align:center;
                 font-size:0.8;
                 font-family:Tahoma;
                 """
    header_cell_style = """
                        border-right:1px solid #595959;
                        border-bottom:1px solid #595959;
                        border-top:1px solid #595959;
                        padding:1em;
                        """
    item_cell_style = """
                      padding:0.75em 0.25em;
                      """
    
    def __init__(self, *args, **kwargs):
        #super(self, AcknowledgementEmail).__init__(*args, **kwargs)
        
        self.start_date = datetime.today()
        self.end_date = self.start_date + timedelta(days=31)
        self.queryset = self.queryset.filter(delivery_date__range=[self.start_date,
                                                                   self.end_date])
        self.queryset = self.queryset.order_by('delivery_date')
        
    def get_message(self):
        #return self.message
        return render_to_string('delivery_email.html', {'acknowledgements': self.queryset,
                                                        'header_style': self.header_cell_style,
                                                        'cell_style': self.cell_style,
                                                        'item_cell_style': self.item_cell_style,
                                                        'start_date': self.start_date,
                                                        'end_date': self.end_date})       
            
            
if __name__ == "__main__":
    email = AcknowledgementEmail()
    message = email.get_message()
    e_conn = boto.ses.connect_to_region('us-east-1')
    e_conn.send_email('noreply@dellarobbiathailand.com',
                      'Delivery Schedule',
                      message,
                      ["charliep@dellarobbiathailand.com"],
                      #["deliveries@dellarobbiathailand.com"],
                      format='html')









