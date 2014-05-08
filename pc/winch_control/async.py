import threading

class OperationAborted(Exception):
    def __init__(self,cleanup=True):
        """
        if cleanup is true, then higher level classes are
        allowed to initiate lower-level actions to finish
        up the job.
        """
        self.cleanup = cleanup
        print "init OperationAborted with cleanup=%s"%self.cleanup

# attempting python decorator to synchronize winch access
# simplify writing asynchronous methods, and centralize
# abort handling
def async(label):
    def async_with_label(f):
        def wrapper(*args,**kw):
            obj = args[0]
            # require block to be specified to keep things clear
            block = kw.pop('block')

            if block:
                try:
                    # calling this async_action is now a misnomer,
                    # but by recording the top level synchronous action,
                    # too, there's more information to convey.
                    if obj.async_action is None:
                        obj.async_action = label
                        clear_action = True
                    else:
                        clear_action = False
                    return f(*args,**kw)
                finally:
                    #print "on the way out of ",label
                    if clear_action:
                        obj.async_action = None

            callback = kw.pop('callback',None)

            def target():
                try:
                    obj.async_action = label
                    try:
                        val = f(*args,**kw)
                        if callback is not None:
                            callback(val)
                        return val
                    except OperationAborted:
                        obj.handle_abort()
                finally:
                    # print "async thread exiting"
                    with obj.lock:
                        obj.thread = None
                        # clear any abort signal
                        obj.abort_async=False
                        obj.async_action = None

            with obj.lock:
                if obj.thread is not None:
                    print "Process already running!"
                    return False
                obj.thread = threading.Thread(target=target)
                obj.thread.setDaemon(1) # don't hold up process exit??
                obj.thread.start()
        return wrapper
    return async_with_label
