# -*- coding: utf-8 -*-
from . import logger
from .hardcover_state_sync import push_book_progress

log = logger.create()

class TaskHardcoverProgressPush:
    def __init__(self, user_id, book_id, source="kobo_state"):
        self.user_id = user_id
        self.book_id = book_id
        self.source = source
        self.name = "Hardcover Progress Push"
        self.message = f"Pushing progress for book {book_id}"

    def run(self):
        from cps.ub import User
        from cps import ub
        user = ub.session.query(User).filter(User.id == self.user_id).first()
        if not user:
            log.error("Hardcover progress push: user %s not found.", self.user_id)
            return

        push_book_progress(user, self.book_id, source=self.source)
        
        # Cleanup session
        from cps import calibre_db
        calibre_db.session.remove()
        ub.session.remove()
