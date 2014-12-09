import logging
from rest_framework import viewsets
from rest_framework import generics
from django.db.models import Q

from products.models import Upholstery, Table, Model, Configuration
from products.serializers import UpholsterySerializer, TableSerializer, ModelSerializer, ConfigurationSerializer


logger = logging.getLogger(__name__)


class ConfigurationViewSet(viewsets.ModelViewSet):
    """
    API endpoint to view and edit configurations
    """
    queryset = Configuration.objects.all()
    serializer_class = ConfigurationSerializer
    
    def get_queryset(self):
        """
        Override 'get_queryset' method in order to customize filter
        """
        queryset = self.queryset
        
        #Filter based on query
        query = self.request.QUERY_PARAMS.get('q', None)
        if query:
            queryset = queryset.filter(Q(configuration__icontains=query))
                                      
        offset = int(self.request.query_params.get('offset', 0))
        limit = int(self.request.query_params.get('limit', settings.REST_FRAMEWORK['PAGINATE_BY']))
        if offset and limit:
            queryset = queryset[offset - 1:limit + (offset - 1)]
            
        return queryset
        
    def get_paginate_by(self):
        """
        
        """
        limit = int(self.request.query_params.get('limit', settings.REST_FRAMEWORK['PAGINATE_BY']))
        if limit == 0:
            return self.queryset.count()
        else:
            return limit
            
            
class ModelViewSet(viewsets.ModelViewSet):
    """
    API endpoint to view and edit models
    """
    queryset = Model.objects.all()
    serializer_class = ModelSerializer

    def get_queryset(self):
        """
        Override 'get_queryset' method in order to customize filter
        """
        queryset = self.queryset
        
        #Filter based on query
        query = self.request.QUERY_PARAMS.get('q', None)
        if query:
            queryset = queryset.filter(Q(name__icontains=query) |
                                       Q(model__icontains=query) |
                                       Q(collection__icontains=query))
                                      
        offset = int(self.request.query_params.get('offset', 0))
        limit = int(self.request.query_params.get('limit', settings.REST_FRAMEWORK['PAGINATE_BY']))
        if offset and limit:
            queryset = queryset[offset - 1:limit + (offset - 1)]
            
        return queryset
        
    def get_paginate_by(self):
        """
        
        """
        limit = int(self.request.query_params.get('limit', settings.REST_FRAMEWORK['PAGINATE_BY']))
        if limit == 0:
            return self.queryset.count()
        else:
            return limit
            
                
class UpholsteryMixin(object):
    queryset = Upholstery.objects.all()
    serializer_class = UpholsterySerializer
    
    def _format_primary_key_data(self, request):
        """
        Format fields that are primary key related so that they may 
        work with DRF
        """
        fields = ['model', 'configuration']
        
        for field in fields:
            if field in request.data:
                if 'id' in request.data[field]:
                    request.data[field] = request.data[field]['id']
                    
        return request
                    
class UpholsteryList(UpholsteryMixin, generics.ListCreateAPIView):
 
    def post(self, request, *args, **kwargs):
        request = self._format_primary_key_data(request)
        return super(UpholsteryList, self).post(request, *args, **kwargs)
        
    def get_queryset(self):
        """
        Override 'get_queryset' method in order to customize filter
        """
        queryset = self.queryset
        
        #Filter based on query
        query = self.request.QUERY_PARAMS.get('q', None)
        if query:
            queryset = queryset.filter(Q(description__icontains=query) |
                                       Q(model__model__icontains=query) |
                                       Q(model__name__icontains=query) |
                                       Q(configuration__configuration__icontains=query))
                                      
        offset = int(self.request.query_params.get('offset', 0))
        limit = int(self.request.query_params.get('limit', settings.REST_FRAMEWORK['PAGINATE_BY']))
        if offset and limit:
            queryset = queryset[offset - 1:limit + (offset - 1)]
            
        return queryset
        
    def get_paginate_by(self):
        """
        
        """
        limit = int(self.request.query_params.get('limit', settings.REST_FRAMEWORK['PAGINATE_BY']))
        if limit == 0:
            return self.queryset.count()
        else:
            return limit
            
                    
class UpholsteryDetail(UpholsteryMixin, generics.RetrieveUpdateDestroyAPIView):
    def put(self, request, *args, **kwargs):
        request = self._format_primary_key_data(request)
        return super(UpholsteryDetail, self).put(request, *args, **kwargs) 
    
    
class UpholsteryViewSet(viewsets.ModelViewSet):
    """
    API endpoint to view and edit table
    """
    queryset = Upholstery.objects.all()
    serializer_class = UpholsterySerializer
    
    
class TableMixin(object):
    queryset = Table.objects.all()
    serializer_class = TableSerializer
    
    def _format_primary_key_data(self, request):
        """
        Format fields that are primary key related so that they may 
        work with DRF
        """
        fields = ['model', 'configuration']
        
        for field in fields:
            if field in request.data:
                if 'id' in request.data[field]:
                    request.data[field] = request.data[field]['id']
                    
        return request
        
                    
class TableList(TableMixin, generics.ListCreateAPIView):
    def post(self, request, *args, **kwargs):
        request = self._format_primary_key_data(request)
        return super(TableList, self).post(request, *args, **kwargs)
        
        
class TableDetail(TableMixin, generics.RetrieveUpdateDestroyAPIView):
    def put(self, request, *args, **kwargs):
        request = self._format_primary_key_data(request)
        return super(TableDetail, self).put(request, *args, **kwargs)
        
        
class TableViewSet(viewsets.ModelViewSet):
    """
    API endpoint to view and edit table
    """
    queryset = Table.objects.all()
    serializer_class = TableSerializer