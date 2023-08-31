from collections import defaultdict


class Page:
    def __init__(self, tab=None):
        self.request_log = []
        self.document_request_log = []
        self.failed_request_log = []
        self.response_log = []
        self.security_state_log = []
        self.scan_start = None
        self.tab = tab
        self._response_lookup = defaultdict(list)
        self._frame_id = None

    def add_request(self, request):
        # We remember if there were requests that changed the displayed
        # document in the current tab (frameId)
        if self._frame_id is None:
            self._frame_id = request['extra']['frameId']
        document_changed = (request['extra']['type'] == 'Document' and
                            request['extra']['frameId'] == self._frame_id and
                            'redirectResponse' not in request['extra'])
        if document_changed:
            self.document_request_log.append(request)

        self.request_log.append(request)

    def add_failed_request(self, failed_request):
        self.failed_request_log.append(failed_request)

    def add_response(self, response):
        self.response_log.append(response)
        self._response_lookup[response['requestId']].append(response)

    def get_final_response_by_id(self, request_id, fail_silently=False):
        response = self.get_response_chain_by_id(request_id, fail_silently)
        return response[-1] if response is not None else None

    def get_response_chain_by_id(self, request_id, fail_silently=False):
        if request_id not in self._response_lookup:
            if fail_silently:
                return None
            raise KeyError('No response for request id {}.'.format(request_id))
        return self._response_lookup[request_id]

    @property
    def final_response(self):
        request_id = self.document_request_log[-1]['requestId']
        return self.get_final_response_by_id(request_id)
    
    def _reset_page(self, tab):
        self.request_log = []
        self.document_request_log = []
        self.failed_request_log = []
        self.response_log = []
        self.security_state_log = []
        self.tab = tab
        self._response_lookup = defaultdict(list)
        self._frame_id = None
