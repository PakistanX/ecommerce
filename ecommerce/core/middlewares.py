import logging
from django.contrib.sites.middleware import CurrentSiteMiddleware
from django.urls import reverse
from django.db import connection
from django.conf import settings
import os

logger = logging.getLogger(__name__)


class SkipSiteMiddleware(CurrentSiteMiddleware):
    """Remove SiteMiddleware if request is for /health."""

    def process_request(self, request):
        if request.path not in reverse('health'):
            logger.info('\n\n\nrequest path: {}\n\n\n'.format(request.path))
            return super().process_request(request)


def terminal_width():
    """
    Function to compute the terminal width.
    """
    width = 0
    try:
        import struct, fcntl, termios
        s = struct.pack('HHHH', 0, 0, 0, 0)
        x = fcntl.ioctl(1, termios.TIOCGWINSZ, s)
        width = struct.unpack('HHHH', x)[1]
    except:
        pass
    if width <= 0:
        try:
            width = int(os.environ['COLUMNS'])
        except:
            pass
    if width <= 0:
        width = 80
    return width


def SqlPrintingMiddleware(get_response):
    def middleware(request):
        response = get_response(request)
        if not settings.DEBUG or len(connection.queries) == 0 or\
            request.path_info.startswith(settings.MEDIA_URL) or \
            '/admin/jsi18n/' in request.path_info:
            return response

        indentation = 2
        print("\n\n%s\033[1;35m[SQL Queries for]\033[1;34m %s\033[0m\n" % (" " * indentation, request.path_info))
        width = terminal_width()
        total_time = 0.0
        for query in connection.queries:
            nice_sql = query['sql'].replace('"', '').replace(',', ', ')
            sql = "\033[1;31m[%s]\033[0m %s" % (query['time'], nice_sql)
            total_time = total_time + float(query['time'])
            while len(sql) > width - indentation:
                print("%s%s" % (" " * indentation, sql[:width - indentation]))
                sql = sql[width - indentation:]
            print("%s%s\n" % (" " * indentation, sql))
        replace_tuple = (" " * indentation, str(total_time))
        print("%s\033[1;32m[TOTAL TIME: %s seconds]\033[0m" % replace_tuple)
        print("%s\033[1;32m[TOTAL QUERIES: %s]\033[0m" % (" " * indentation, len(connection.queries)))
        return response
    return middleware
