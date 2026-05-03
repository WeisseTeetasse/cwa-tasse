# -*- coding: utf-8 -*-

from flask_babel import lazy_gettext as N_

from cps import logger, ub, calibre_db
from cps.hardcover_state_sync import push_book_progress
from cps.services.worker import CalibreTask


class TaskHardcoverProgressPush(CalibreTask):
    def __init__(self, user_id, book_id, task_message=None, source="kobo_state"):
        super(TaskHardcoverProgressPush, self).__init__(
            task_message or N_("Hardcover progress push")
        )
        self.log = logger.create()
        self.user_id = int(user_id)
        self.book_id = int(book_id)
        self.source = source
        self.progress = 0

    @property
    def name(self):
        return N_("Hardcover Progress Push")

    @property
    def is_cancellable(self):
        return False

    def run(self, worker_thread):
        try:
            user = ub.session.query(ub.User).filter(
                ub.User.id == self.user_id
            ).first()

            if not user:
                self._handleError(f"User {self.user_id} not found")
                return

            self.progress = 0.2
            push_book_progress(user, self.book_id, source=self.source)
            self.progress = 1.0
            self._handleSuccess()

        except Exception as e:
            self.log.error(
                "Hardcover progress push failed for user %s book %s: %s",
                self.user_id,
                self.book_id,
                e,
                exc_info=True,
            )
            self._handleError(str(e))

        finally:
            try:
                calibre_db.session.remove()
            except Exception:
                pass
            try:
                ub.session.remove()
            except Exception:
                pass
