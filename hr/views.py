import logging
import json
from dateutil import parser
import pytz
from threading import Thread
from time import sleep
from datetime import time, datetime

import boto
from django.template.loader import render_to_string
from django.db.models import Q
from django.http import HttpResponseRedirect, HttpResponse
from rest_framework import generics
from rest_framework import viewsets
from django.conf import settings

from hr.serializers import EmployeeSerializer, AttendanceSerializer, ShiftSerializer, PayrollSerializer
from utilities.http import save_upload
from auth.models import S3Object
from hr.models import Employee, Attendance, Timestamp, Shift, Payroll


logger = logging.getLogger(__name__)


def employee_stats(request):
    employees = Employee.objects.filter(status="active", company="alinea group")
    
    cursor = connection.cursor()
    query = """
    SELECT SUM(SELECT )
    """
    
    cursor.execute(query)
    row = cursor.fetchone()
    
    data = {'acknowledged': {'count': row[0], 'amount': str(row[1])},
            'in_production': {'count':row[2], 'amount': str(row[3])},
            'ready_to_ship': {'count': row[4], 'amount': str(row[5])},
            'shipped': {'count':row[6], 'amount': str(row[7])},
            'invoiced': {'count': row[8], 'amount': str(row[9])},
            'paid': {'count': row[10], 'amount': str(row[11])},
            'deposit_received': {'count': row[12], 'amount': str(row[13])},
            'total': {'count': row[-2], 'amount': str(row[-1])}}
            
    response = HttpResponse(json.dumps(data),
                            content_type="application/json")
    response.status_code = 200
    return response
    

def upload_attendance(request):
    if request.method == "POST":
        file = request.FILES.get('file')
        
        with open('attendance.txt', 'wb+') as destination:
            for chunk in file.chunks():
                destination.write(chunk)
        
        # Save and format the data into a list
        lines = open('attendance.txt').readlines()
        data = [l.replace('\r\n', '').split('\t') for l in lines]
        
        assert len(lines) == len(data), "Error reformatting data from attendance.txt"

        # Create master holders
        timestamps = []
        error_times = []
        employees = {}
        missing_employees = {}
        duplicate_employees = []
        timezone = pytz.timezone('Asia/Bangkok')
        employee_queryset = Employee.objects.filter(status='active').select_related('shift')
        timestamp_queryset = Timestamp.objects.all().select_related('employee', 'employee__shift')

        def create_timestamps(data):
            """
            Create Timestamps

            This function will loop through the list of data, and 
            find a timestamp if it exists. If not it will create a new 
            timestamp
            """
            for index, d in enumerate(data):
                employee = None
                timestamp = timezone.localize(parser.parse(d[-1]))
                card_id = d[2]
                
                # Find the employee with the corresponding card id
                try:
                    # Check if employee is already found and in the dict
                    if card_id in employees:
                        employee = employees[card_id]
                    # Retrieves employee by card id and active status
                    else:
                        employee = employee_queryset.get(card_id=card_id)
                        employees[employee.card_id] = employee

                except IndexError as e:
                    print '\n\n'
                    missing_employees[card_id] = {'id': d[2], 'timestamp': timestamp, 'card_id': card_id}
                    logger.debug('No employee for card ID {0} on date: {1}'.format(card_id, timestamp))
                    print '\n\n'
                except Employee.DoesNotExist:
                    missing_employees[card_id] = {'id': d[2], 'timestamp': timestamp, 'card_id': card_id}
                    logger.debug('No employee for card ID {0} on date: {1}'.format(card_id, timestamp))
                except Employee.MultipleObjectsReturned as e:
                    duplicate_employees.append({'id': d[2], 'timestamp': timestamp})
                    logger.debug("Card ID {0} return model than 1 employee".format(card_id))
                
                if employee:
                    # Try to find an existing time stamp first
                    try:
                        timestamps.append(timestamp_queryset.objects.get(employee=employee, datetime=timestamp))
                    # Creates a timestamp if one is not found
                    except Timestamp.DoesNotExist as e:
                        timestamps.append(Timestamp.objects.create(employee=employee,
                                                                     datetime=timestamp))
                    # If multiple copies are found, all are deleted and new one is made
                    except Timestamp.MultipleObjectsReturned as e:
                        Timestamp.objects.filter(employee=employee, datetime=timestamp).delete()
                        timestamps.append(Timestamp.objects.create(employee=employee,
                                                                     datetime=timestamp))

                                                                 
            
        def create_attendances(timestamps):
            for t in timestamps:
                count = Attendance.objects.filter(employee=t.employee, date=t.datetime.date()).count()
                if count == 0:
                    attendance = Attendance.objects.create(employee=t.employee, date=t.datetime.date(), 
                                                           shift=t.employee.shift, pay_rate=t.employee.wage)
                elif count == 1:
                    attendance = Attendance.objects.get(employee=t.employee, date=t.datetime.date())
                elif count > 1:
                    Attendance.objects.filter(employee=t.employee, date=t.datetime.date()).delete()
                    attendance = Attendance.objects.create(employee=t.employee, date=t.datetime.date(), 
                                                           shift=t.employee.shift, pay_rate=t.employee.wage)
                    
            
                if t.time.hour < t.employee.shift.start_time.hour + 4:
                    attendance.start_time = t.time
                else:
                    attendance.end_time = t.time
                attendance.save()
                
                assert attendance.id is not None
                assert attendance.date is not None
                assert attendance.employee is not None
                assert attendance.date.year == 2018
                #logger.debug("{0}: {1} | {2}".format(attendance.date, attendance.employee.id, attendance.id))
        
            
        def create_timestamps_and_attendances(data):
            logger.debug("Total timestamps {0}".format(len(data)))
            data1 = data[1:len(data)/2]
            data2 = data[len(data)/2:]

            # Check that the timestamps have been divided correctly
            assert len(data1) + len(data2) == len(data) - 1, "Data quantities do not match"

            thread1 = Thread(target=create_timestamps, args=(data1, ))
            thread2 = Thread(target=create_timestamps, args=(data2, ))
        
            threads = [thread1, thread2]
        
            thread1.start()
            thread2.start()
        
            while len([t for t in threads if t.isAlive()]) > 0:
                sleep(100)
                
            create_attendances(timestamps)
            
            logger.debug("Emailing Attenance Upload Report")

            heading = """Attendance Upload Report"""
            header_cell_style = """
                                border-right:1px solid #595959;
                                border-bottom:1px solid #595959;
                                border-top:1px solid #595959;
                                padding:1em;
                                text-align:center;
                                """
            message = render_to_string("attendance_upload_email.html", 
                                       {'heading': heading,
                                        'header_style': header_cell_style,
                                        'missing_employees': missing_employees,
                                        'duplicate_employees': duplicate_employees})
    
            e_conn = boto.ses.connect_to_region('us-east-1')
            e_conn.send_email('noreply@dellarobbiathailand.com',
                              'Attendance Upload Report',
                              message,
                              ["hr@alineagroup.co"],
                              format='html')
            
            
            
        # Primary parallel thread
        primary_thread = Thread(target=create_timestamps_and_attendances, args=(data, ))
        primary_thread.start()
        
                
        response = HttpResponse(json.dumps({'status': 'We will send you an email once the upload has completed.'}),
                                content_type="application/json")
        response.status_code = 201
        return response
            
        
def employee_image(request):
    if request.method == "POST":
        filename = save_upload(request)
        obj = S3Object.create(filename,
                        "employee/image/{0}.jpg".format(datetime.now().microsecond),
                        'media.dellarobbiathailand.com')
        response = HttpResponse(json.dumps({'id': obj.id,
                                            'url': obj.generate_url()}),
                                content_type="application/json")
        response.status_code = 201
        return response
        
        
class EmployeeMixin(object):
    queryset = Employee.objects.all().order_by('name')
    serializer_class = EmployeeSerializer
    
    def _format_primary_key_data(self, request):
        """
        Format fields that are primary key related so that they may 
        work with DRF
        """
        fields = ['image']
        
        for field in fields:
            if field in request.data:
                try:
                    if 'id' in request.data[field]:
                        request.data[field] = request.data[field]['id']
                except TypeError:
                    pass
                                    
        return request
        
    
class EmployeeList(EmployeeMixin, generics.ListCreateAPIView):
    
    def post(self, request, *args, **kwargs):
        request = self._format_primary_key_data(request)
        response = super(EmployeeList, self).post(request, *args, **kwargs)
        
        return response
        
    def get_queryset(self):
        """
        Override 'get_queryset' method in order to customize filter
        """
        queryset = self.queryset.all().order_by('status', 'government_id', 'card_id', 'name')
        
        #Filter based on query
        query = self.request.query_params.get('q', None)
        status = self.request.query_params.get('status', None)
        offset = int(self.request.query_params.get('offset', 0))
        limit = int(self.request.query_params.get('limit', settings.REST_FRAMEWORK['PAGINATE_BY']))

       
        if query:
            queryset = queryset.filter(Q(id__icontains=query) |
                                    Q(first_name__icontains=query) |
                                    Q(last_name__icontains=query) |
                                    Q(card_id__icontains=query) |
                                    Q(name__icontains=query) |
                                    Q(nickname__icontains=query) |
                                    Q(department__icontains=query) |
                                    Q(telephone__icontains=query))
                                    
        
        logger.debug(status)
        if status:
            queryset = queryset.filter(status__icontains=status)
        logger.debug(queryset.count())   
        if offset != None and limit == 0:
            queryset = queryset[offset:]
        elif offset == 0 and limit != 0:
            queryset = queryset[offset:offset + limit]
        else:
            queryset = queryset[offset: offset + settings.REST_FRAMEWORK['PAGINATE_BY']]
        
        queryset = queryset.select_related('shift',
                                           'image')
        queryset = queryset.prefetch_related('equipments')
        return queryset
    
    
class EmployeeDetail(EmployeeMixin, generics.RetrieveUpdateDestroyAPIView):
    def put(self, request, *args, **kwargs):
        request = self._format_primary_key_data(request)
        response = super(EmployeeDetail, self).put(request, *args, **kwargs)
        
        return response
    
    
class AttendanceMixin(object):
    queryset = Attendance.objects.all().order_by('-id')
    serializer_class = AttendanceSerializer
    
    
class AttendanceList(AttendanceMixin, generics.ListCreateAPIView):
    
    
    def post(self, request, *args, **kwargs):
        
        tz = pytz.timezone('Asia/Bangkok')
        
        a_date = parser.parse(request.data['date']).astimezone(tz).date()
        request.data['date'] = a_date
        
        s_time = parser.parse(request.data['start_time'])
        s_time = s_time.astimezone(tz)
        s_time = datetime.combine(a_date, s_time.timetz())
        request.data['start_time'] = s_time
        
        e_time = parser.parse(request.data['end_time'])
        e_time = e_time.astimezone(tz)
        e_time = datetime.combine(a_date, e_time.timetz())
        request.data['end_time'] = e_time
        
        try:
            o_time = parser.parse(request.data['overtime_request'])
            o_time = tz.localize(o_time)
            o_time = datetime.combine(a_date, o_time.timetz())
            request.data['overtime_request'] = o_time
        except ValueError as e:
            logger.debug(e)
            o_time = parser.parse(request.data['overtime_request'])
            o_time = datetime.combine(a_date, o_time.timetz())
            logger.debug(o_time)
            request.data['overtime_request'] = o_time
        except KeyError as e:
            logger.warn(e)
        
        response = super(AttendanceList, self).post(request, *args, **kwargs)
        
        return response
            
    def get_queryset(self):
        """
        Override 'get_queryset' method in order to customize filter
        """
        queryset = self.queryset.order_by('date')

        # Eager loading
        #queryset = self.get_serializer_class().setup_eager_loading(queryset)
        
        offset = int(self.request.query_params.get('offset', 0))
        limit = int(self.request.query_params.get('limit', settings.REST_FRAMEWORK['PAGINATE_BY']))
        start_date = self.request.query_params.get('start_date', None)
        end_date = self.request.query_params.get('end_date', None)
        employee_id = self.request.query_params.get('employee_id', None)
        
        if employee_id or (start_date and end_date):
            query = "SELECT * FROM hr_attendance WHERE"

            # Search only attendances for selected employee
            if employee_id:
                queryset = queryset.filter(employee_id=employee_id)
                query += " employee_id = {0}".format(employee_id)
            
            # Filter all records after the start_date
            if start_date and end_date:
                start_date = parser.parse(start_date)
                start_date_str = start_date.strftime("%Y-%m-%d")
                end_date = parser.parse(end_date)
                end_date_str = end_date.strftime("%Y-%m-%d")
                
                queryset = queryset.filter(date__range=[start_date_str, end_date_str])
            #queryset = Attendance.objects.raw(query)
    
        if offset != None and limit == 0:
            queryset = queryset[offset:]
        elif offset == 0 and limit != 0:
            queryset = queryset[offset:offset + limit]
        else:
            queryset = queryset[offset: offset + settings.REST_FRAMEWORK['PAGINATE_BY']]

        queryset = queryset.select_related('shift', 'employee__shift')
        #queryset = queryset.prefetch_related('employee__shift')

        return queryset
    
    
class AttendanceDetail(AttendanceMixin, generics.RetrieveUpdateDestroyAPIView):
    
    def put(self, request, *args, **kwargs):
        
        tz = pytz.timezone('Asia/Bangkok')
        
        a_date = parser.parse(request.data['date']).astimezone(tz).date()
        request.data['date'] = a_date
        
        try:
            s_time = parser.parse(request.data['start_time'])
            s_time = s_time.astimezone(tz)
            s_time = datetime.combine(a_date, s_time.timetz())
            request.data['start_time'] = s_time
        except AttributeError as e:
            pass
        
        try:
            e_time = parser.parse(request.data['end_time'])
            e_time = e_time.astimezone(tz)
            e_time = datetime.combine(a_date, e_time.timetz())
            request.data['end_time'] = e_time
        except AttributeError as e:
            pass
        
        try:
            o_time = parser.parse(request.data['overtime_request'])
            o_time = o_time.astimezone(tz)
            o_time = datetime.combine(a_date, o_time.timetz())
            request.data['overtime_request'] = o_time
        except (KeyError, AttributeError) as e:
            logger.warn(e)
        
        response = super(AttendanceDetail, self).put(request, *args, **kwargs)
        
        return response
    
    
class ShiftViewSet(viewsets.ModelViewSet):
    """
    API endpoint to view and edit configurations
    """
    queryset = Shift.objects.all()
    serializer_class = ShiftSerializer
    
    
class PayrollList(generics.ListCreateAPIView):
    queryset = Payroll.objects.all().order_by('-id')
    serializer_class = PayrollSerializer
    