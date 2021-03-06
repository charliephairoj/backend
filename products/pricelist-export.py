#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys, os, django
sys.path.append('/Users/Charlie/Sites/employee/backend')
os.environ['DJANGO_SETTINGS_MODULE'] = 'EmployeeCenter.settings'
from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
import logging
import math
from decimal import *
import re
import csv
import multiprocessing
from threading import Thread
from time import sleep
from operator import itemgetter

from django.conf import settings
from django.core.exceptions import *
from django.db.models import Q, Sum
from reportlab.lib import colors, utils
from reportlab.lib.units import mm
from reportlab.platypus import *
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.graphics.barcode import code128
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from svglib.svglib import svg2rlg

from products.models import Model, Upholstery, Supply as ProductSupply
from supplies.models import Fabric
from contacts.models import Supplier


django.setup()

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


pdfmetrics.registerFont(TTFont('Tahoma', settings.FONT_ROOT + 'Tahoma.ttf'))
pdfmetrics.registerFont(TTFont('Garuda', settings.FONT_ROOT + 'Garuda.ttf'))


class PricelistDocTemplate(BaseDocTemplate):
    id = 0
    top_padding = 36 #150


    def __init__(self, filename, **kwargs):

        BaseDocTemplate.__init__(self, filename, **kwargs)
        self.addPageTemplates(self._create_page_template())

    def _create_page_template(self):
        frame = Frame(0, 0, 210 * mm, 297 * mm, leftPadding=36,
                      bottomPadding=30, rightPadding=36,
                      topPadding=self.top_padding)
        template = PageTemplate('Normal', [frame])
        template.beforeDrawPage = self._create_header
        return template

    def _create_header(self, canvas, doc):
        #Draw the logo in the upper left
        path = """form_logo.jpg"""

        img = utils.ImageReader(path)
        #Get Size
        img_width, img_height = img.getSize()
        new_width = (img_width * 30) / img_height
        #canvas.drawImage(path, 42, 780, height=30, width=new_width)

        canvas.setFont('Times-Roman', 5)
        canvas.drawString(565, 4, "Page {0}".format(doc.page))


class PricelistPDF(object):
    models = [
        'AC-2005',
        'AC-2008',
        'AC-2015',
        'AC-2021',
        #'AC-2023',
        'AC-2027',
        'AC-2029',
        'AC-2033',
        'AC-2042',
        #'AC-2043',
        'AC-2051',
        #'AC-2055',
        'AC-2080',
        'AC-2082',
        'AC-2086',
        'AC-2090',
        #'AC-2091',
        #'AC-2093',
        'AC-2106',
        'AC-2108',
        #'AC-2110',
        'AC-2118',
        #'AC-2123',
        'AC-2137',
        'AC-2142',
        'AC-2157',
        'AC-2159',
        'PS-905',
        #'PS-605',
        'PS-1019',
        'PS-1024',
        'PS-1028',
        'PS-1029',
        #'PS-1031'
    ]
    queryset = Model.objects.filter(Q(model__in=models))
    #queryset = Model.objects.filter(Q(model__istartswith='dw-') | Q(model__in=models))
    #queryset = Model.objects.filter(Q(model__istartswith='ac-'))
    #queryset = queryset.filter(upholstery__id__gt=0).distinct('model').order_by('model')
    #queryset = queryset.exclude(model__icontains="DA-")
    #queryset = queryset.exclude(model='DW-1217').exclude(model='DW-1212')
    #data = [m for m in queryset.filter(model__istartswith='dw-')]
    #data += [m for m in queryset.exclude(model__istartswith='dw-').order_by('model')]
    _display_retail_price = False
    _overhead_percent = 30
    _profit_percent = 35
    _forex_rate = 36 #Forex rate for THB per USD
    _preface = {'General Information': {'Conditions of Sale': 'conditions_of_sale.txt',
                                        'Terms': 'terms.txt',
                                        'Order Processing': 'order_processing.txt',
                                        'Acknowledging': 'acknowledging.txt',
                                        'Delivery': 'delivery.txt'},
                 'Warranty': {'Warranty': 'warranty.txt',
                              'Fabrics': 'fabrics.txt'},
                 'Product Information': {'Custom Sizes': 'custom_sizes.txt'}}

    table_style = [('GRID', (0, 0), (-1,-1), 1, colors.CMYKColor(black=60)),
                   ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                   ('FONT', (0,0), (-1,-1), 'Garuda'),
                   ('TEXTCOLOR', (0,0), (-1,-1), colors.CMYKColor(black=60)),
                   ('ALIGNMENT', (0,0), (-1,-1), 'LEFT'),
                   ('ALIGNMENT', (2,0), (2,-1), 'CENTER'),
                   ('PADDING', (0,0), (-1,-1), 0),
                   ('FONTSIZE', (0,0),(-1,-1), 10)]

    def __init__(self, *args, **kwargs):

        self.export = True
        self.fabrics = fabrics

    def create(self, filename='Pricelist.pdf'):
        filename = filename if not self.export else "Pricelist_Export.pdf"

        doc = PricelistDocTemplate(filename,
                                   pagesize=A4,
                                   leftMargin=12,
                                   rightMargin=12,
                                   topMargin=12,
                                   bottomMargin=12)
        stories = []


        stories.append(Spacer(0, 200))
        link = "form_logo.jpg"
        stories.append(self._get_image(link, width=200))
        stories.append(PageBreak())

        logger.debug("\n\nProcessing Terms and Conditions\n\n")

        for category in ['General Information', 'Warranty', 'Product Information']:

            stories.append(self._prepare_text("<u>" + category + "</u>", alignment=TA_LEFT, font_size=18, fontname="Helvetica-Bold"))
            stories.append(Spacer(0, 20))

            for key in self._preface[category]:

                text = self._extract_text('texts/' + self._preface[category][key])
                stories.append(self._prepare_text(key, alignment=TA_LEFT, font_size=16, fontname="Helvetica-Bold", left_indent=20))
                stories.append(Spacer(0, 10))
                stories.append(self._prepare_text(text, alignment=TA_LEFT, font_size=14, left_indent=40, leading=20))
                stories.append(Spacer(0, 25))

            stories.append(PageBreak())

        logger.debug("\n\nProcessing {0} Models\n\n\n\n".format(self.queryset.count()))

        models = self._prepare_data(self.queryset)

        models_name = [model for model in sorted(models.keys(), key=lambda model: model.model) if "DW-" in model.model]
        models_name += [model for model in sorted(models.keys(), key=lambda model: model.model) if "DW-" not in model.model]

        # Adding models to the document. 
        for model in models_name:
            stories.append(self._create_model_page(model, models[model]))
            #stories.append(self._create_model_section(model, models[model]))
            stories.append(PageBreak())

        for story in stories:
            try:
                story.hAlign = "CENTER"
            except AttributeError:
                pass


        doc.build(stories)

    def _prepare_data(self, models):

        data = {}
        threads = []
        for model in models:
            data[model] = {}

            t = Thread(target=self._add_upholstery_data, args=(model, data))
            threads.append(t)
            t.start()

        while len([t for t in threads if t.isAlive()]) > 0:
            sleep(1)

        else:
            return data

    def _add_upholstery_data(self, model, data):


        for upholstery in Upholstery.objects.filter(model=model).exclude(description__icontains="pillow").distinct('description').order_by('description'):

            uphol_data = {'id': upholstery.id,
                          'configuration': upholstery.configuration.configuration,
                          'description': upholstery.description,
                          'width': upholstery.width,
                          'depth': upholstery.depth,
                          'height': upholstery.height,
                          'price': upholstery.price,
                          'export_price': upholstery.export_price}

            try:
                uphol_data['schematic'] = upholstery.schematic
            except AttributeError:
                logger.warn("Upholstery: {0} is missing schematics".format(upholstery.description))

            config_key = upholstery.configuration.configuration.lower()
            config_key = config_key.replace(' right', '').replace('right', '')
            config_key = config_key.replace(' left', '').replace('left', '')
            config_key = config_key.replace('-', ' ').strip()
            config_key = " ".join([s.capitalize() for s in config_key.split(' ')])
            data[model][config_key] = uphol_data

    def _create_model_page(self, model, products):
        # Initial array and image of product
        images = model.images.all().order_by('-primary')

        # Create data array used to create table
        data = [[model.model]]
        # Add Image for this model
        try:
            data.append([self._get_image(images[0].generate_url(), height=150)])
        except IndexError as e:
            data.append([''])
            logger.warn("Model {0} is missing an image".format(model.model))
        
        # Add title
        data.append(['Schematic', 'Configuration', 'Width', 'Depth' ,'Height', 'Price'])

        # Add upholstery
        products = [(k, products[k]) for k in products]
        for config, product in sorted(products, key=lambda t: (t[1]['depth'], t[1]['width'])):
            
            width = product['width']
            depth = product['depth']
            height = product['height']

            price = product['export_price']
            price = Decimal(str(math.ceil((price * Decimal('1.3')) / Decimal('10')))) * Decimal('10')
            price = "{0}".format(int(price or 0))
            
            filename = "temp/{0}.svg".format(product['description'].replace(' ', '_'))
            try:
                #product['schematic'].download(filename)
                drawing = svg2rlg(filename)
                scale = (40 / drawing.height)
                #drawing.scale(scale, scale)
                drawing.vAlign = 'TOP'
                drawing.renderScale = scale
                data.append([drawing, config, width, depth, height, price])
            except AttributeError as e:
                try:
                    product['schematic'].download(filename)
                except AttributeError as e:
                    logger.warn("{0} has no schematics".format(product['description']))
                logger.warn("Error getting schematics for {0}".format(product['description']))
                data.append(['', config, width, depth, height, price])

        # Calculate the rowHeights
        row_heights = [50, 150]
        row_heights += [45 for i in xrange(len(products) + 1)]
        table = Table(data, colWidths=(100, 200, 60, 60, 60, 75), rowHeights=row_heights)
        table_style = TableStyle([('FONTSIZE', (0, 0), (0, 0), 20),
                                  ('FONTSIZE', (0, 0), (-1, 2), 16),
                                  #('GRID', (0, 0), (-1, -1), 1, 'RED'),
                                  ('ALIGNMENT', (0,0), (-1, 1), 'CENTER'),
                                  ('ALIGNMENT', (2,3), (-1, -1), 'CENTER'),
                                  ('ALIGNMENT', (2,2), (-1, 2), 'CENTER'),
                                  ('ALIGNMENT', (-1,3), (-1, -1), 'RIGHT'),
                                  ('VALIGN', (0, 2), (0, -1), 'TOP'),
                                  ('PADDING', (0,0), (-1, 0), 10),
                                  ('RIGHTPADDING', (-1,3), (-1, -1), 30),
                                  ('SPAN', (0, 0), (-1, 0)),
                                  ('SPAN', (0, 1), (-1, 1)),
                                  #('GRID', (0, 0), (-1, -1), 1, 'red'),
                                  #('LEFTPADDING', (0, 0), (-1, -1), 0),
                                  ('VALIGN', (0, 0), (-1, -1), 'MIDDLE')])
        table.setStyle(table_style)

        return table

    def _create_model_section(self, model, products):
 
        """
        Create a table of prices for all the products in this model
        """
        # Products for this model
        #products = Upholstery.objects.filter(model=model, supplies__id__gt=0).distinct('description').order_by('description')

        # Initial array and image of product
        images = model.images.all().order_by('-primary')

        try:
            data = [[self._prepare_text(model.model,
                                        fontname='Helvetica',
                                        alignment=TA_LEFT,
                                        font_size=24,
                                        left_indent=12)],[self._get_image(images[0].generate_url(), height=150)]]
        except IndexError:
            data = [['test']]

        #data = [[self._prepare_text(model.model, font_size=24, alignment=TA_LEFT)]]

        # Var to keep track of number of products priced
        count = 0

        for index in xrange(0, int(math.ceil(len(products) / float(4)))):

            section_products = products
            # Count number of products priced
            count += len(section_products)

            section = self._create_section(section_products, index)
            data.append([section])

        # Check that all products for this model have been priced
        #assert count == len(products), "Only {0} of {1} price".format(count, len(products))

        table_style = [('ALIGNMENT', (0,0), (0, 0), 'CENTER'),
                       ('ALIGNMENT', (0, 1), (0, -1), 'LEFT'),
                       ('PADDING', (0, 1), (-1, -1), 0),
                       ('BOTTOMPADDING', (0, 0), (-1, -1), 30),
                       ('LEFTPADDING', (0, 1), (0, -1), 15)]

        table = Table(data, colWidths=(550))
        table.setStyle(TableStyle(table_style))
        return table

    def _create_section(self, products, index):

        data = []
        for index, config in enumerate(products):
            if index < 5:
                product = products[config]
                data.append([svg2rlg('armless-sofa.svg'), config, product['export_price']])
       

        table = Table(data)
        table.setStyle(TableStyle([('GRID', (0, 0), (-1, -1), 1, colors.CMYKColor(black=60)),
                                   ('LEFTPADDING', (0, 0), (-1, -1), 0),
                                   ('VALIGN', (0, 0), (-1, -1), 'MIDDLE')]))

        return table

    def _create_product_price_table(self, product):
        """
        Calculate price list for each product
        """
        data  = [["W:{0} x D:{1} x H:{2}".format(product['width'], product['depth'], product['height'])]]
        #data  = []
        #prices = product['prices']

        data.append([product['export_price']])
        logger.debug(data)
        table = Table(data, colWidths=(120,))
        table.setStyle(TableStyle([('ALIGNMENT', (0, 0), (-1, -1), 'CENTER'),
                                   ('INNERGRID', (0, 0), (-1, -1), 1, colors.CMYKColor(black=60)),
                                   #('TEXTCOLOR', (0, -1), (-1, -1), 'red')
                                   ]))
        return table

    def _prepare_text(self, description, font_size=12, alignment=TA_CENTER, left_indent=0, fontname='Garuda', leading=12):

        text = description if description else u""
        style = ParagraphStyle(name='Normal',
                               alignment=alignment,
                               fontName=fontname,
                               fontSize=font_size,
                               textColor=colors.CMYKColor(black=60),
                               leftIndent=left_indent,
                               leading=leading)
        return Paragraph(text, style)

    def _extract_text(self, filename):

        file = open(filename)
        txt = file.read()

        return txt

    #helps change the size and maintain ratio
    def _get_image(self, path, width=None, height=None, max_width=0, max_height=0):
        """Retrieves the image via the link and gets the
        size from the image. The correct dimensions for
        image are calculated based on the desired with or
        height"""

        try:
            #Read image from link
            img = utils.ImageReader(path)
        except Exception as e:
            logger.debug(e)
            return ''

        #Get Size
        imgWidth, imgHeight = img.getSize()
        #Detect if there height or width provided
        if width and height == None:
            ratio = float(imgHeight) / float(imgWidth)
            new_height = ratio * width
            new_width = width
        elif height and width == None:
            ratio = float(imgWidth) / float(imgHeight)
            new_height = height
            new_width = ratio * height
            if max_width != 0 and new_width > max_width:
                new_width = max_width
                new_height = (float(imgHeight) / float(imgWidth)) * max_width

        return Image(path, width=new_width, height=new_height)


class FabricPDF(object):

    table_style = [('GRID', (0, 0), (-1,-1), 1, colors.CMYKColor(black=60)),
                   ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                   ('FONT', (0,0), (-1,-1), 'Garuda'),
                   ('TEXTCOLOR', (0,0), (-1,-1), colors.CMYKColor(black=60)),
                   ('ALIGNMENT', (0,0), (-1,-1), 'LEFT'),
                   ('ALIGNMENT', (2,0), (2,-1), 'CENTER'),
                   ('PADDING', (0,0), (-1,-1), 0),
                   ('FONTSIZE', (0,0),(-1,-1), 10)]

    def __init__(self, fabrics=None, *args, **kwargs):

        if fabrics:
            self.fabrics = fabrics
        else:
            fabrics = Fabric.objects.filter(status='current')

            self.fabrics = {}

            for fabric in fabrics:
                fabric.supplier = fabric.suppliers.all()[0]

                try:
                    self.fabrics[fabric.pattern.lower()].append(fabric)
                except (AttributeError, KeyError):
                    self.fabrics[fabric.pattern.lower()] = [fabric]

    def create(self, filename="Fabrics.pdf"):
        doc = SimpleDocTemplate(filename,
                                pagesize=A4,
                                leftMargin=12,
                                rightMargin=12,
                                topMargin=12,
                                bottomMargin=12)
        stories = []

        stories.append(self._create_section())
        stories.append(PageBreak())

        fabrics = {}
        supplier = Supplier.objects.get(name__istartswith='crevin')
        for fabric in Fabric.objects.filter(suppliers__name__istartswith='crevin'):
            fabric.status = 'current'
            fabric.save()

            fabric.supplier = supplier
            try:
                fabrics[fabric.pattern.lower()].append(fabric)
            except KeyError:
                fabrics[fabric.pattern.lower()] = [fabric]

        stories.append(self._create_section(fabrics=fabrics))
        for story in stories:
            story.hAlign = "CENTER"

        doc.build(stories)

    def _create_section(self, fabrics=None):

        fabrics = fabrics or self.fabrics
        data = [[self._prepare_text('Pattern'), self._prepare_text('Color')]]

        keys = fabrics.keys()
        keys.sort()

        for pattern in keys:
            supplier = fabrics[pattern][0].supplier
            data.append([self._prepare_text(pattern.title(), alignment=TA_LEFT),
                         self._create_color_section(fabrics[pattern])])




        table = Table(data, colWidths=(200, 300), repeatRows=1)
        table.setStyle(TableStyle([('GRID', (0, 0), (-1, -1), 1, colors.CMYKColor(black=60)),
                                   ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                                   ('ALIGNMENT', (0, 0), (-1, -1), 'CENTER'),
                                   ('ALIGNMENT', (0, 1), (0, -1), 'LEFT')]))

        return table

    def _create_color_section(self, fabrics):

        data = []

        for fabric in fabrics:

            try:
                data.append([self._get_image(fabric.image.generate_url(), width=100) if fabric.image else '',
                             fabric.color.title(),
                             self._calculate_grade(fabric)])
            except ValueError as e:
                logger.warn(e)
                raise ValueError("{0} : {1}".format(fabric.description, fabric.supplier.name))

        table = Table(data, colWidths=(125, 125, 50))
        table.setStyle(TableStyle([('ALIGNMENT', (-1, 0), (-1, -1), 'CENTER'),
                                   ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                                   ('ALIGNMENT', (0, 0), (0, -1), 'LEFT')]))

        return table

    def _calculate_grade(self, fabric):
        cost = fabric.cost

        if 'Dellarobbia' in fabric.supplier.name:

            if cost > 0:
                cost += Decimal('10')

                cost = math.ceil(cost)
        elif 'crevin' in fabric.supplier.name.lower():

            if cost > 0:
                cost += Decimal('10')

                cost = math.ceil(cost)
        else:

            if cost > 0:
                cost += Decimal('5')

                cost = math.ceil(cost)

        if cost == 0 or cost == 'NA':
            grade = 'NA'
        elif 0 < cost <= 15 :
            grade = 'A1'
        elif cost <= 20:
            grade = 'A2'
        elif cost <= 25:
            grade = 'A3'
        elif cost <= 30:
            grade = 'A4'
        elif cost <= 35:
            grade = 'A5'
        elif cost <= 40:
            grade = 'A6'
        elif cost <= 45:
            grade = 'A7'
        elif cost <= 50:
            grade = 'A8'
        else:
            raise ValueError("cost is {0} for {1}".format(cost, fabric.description))


        fabric.grade = grade
        fabric.save()

        return grade

    def _prepare_text(self, description, font_size=9, alignment=TA_CENTER):

        text = description if description else u""
        style = ParagraphStyle(name='Normal',
                               alignment=alignment,
                               fontName='Garuda',
                               fontSize=font_size,
                               textColor=colors.CMYKColor(black=60))
        return Paragraph(text, style)

    #helps change the size and maintain ratio
    def _get_image(self, path, width=None, height=None, max_width=0, max_height=0):
        """Retrieves the image via the link and gets the
        size from the image. The correct dimensions for
        image are calculated based on the desired with or
        height"""
        try:
            #Read image from link
            img = utils.ImageReader(path)
        except Exception as e:
            logger.debug(e)
            return None

        #Get Size
        imgWidth, imgHeight = img.getSize()
        #Detect if there height or width provided
        if width and height == None:
            ratio = float(imgHeight) / float(imgWidth)
            new_height = ratio * width
            new_width = width
        elif height and width == None:
            ratio = float(imgWidth) / float(imgHeight)
            new_height = height
            new_width = ratio * height
            if max_width != 0 and new_width > max_width:
                new_width = max_width
                new_height = (float(imgHeight) / float(imgWidth)) * max_width

        return Image(path, width=new_width, height=new_height)


if __name__ == "__main__":

    directory = sys.argv[1]

    fabrics = {}
    data = {}
    f_list = []

    if not os.path.exists(directory):
        os.makedirs(directory)

    def create_pricelist(filename):
        pdf = PricelistPDF()
        pdf.create(filename)

    def create_fabriclist(filename, fabrics):
        f_pdf = FabricPDF(fabrics=None)
        f_pdf.create(filename)

    p1 = multiprocessing.Process(target=create_pricelist, args=(directory + '/Pricelist.pdf', ))
    p1.start()
    #p2 = multiprocessing.Process(target=create_fabriclist, args=(directory + '/Fabrics.pdf', fabrics ))
    #p2.start()
