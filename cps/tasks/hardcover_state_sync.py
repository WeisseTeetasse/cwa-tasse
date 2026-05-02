# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

from flask_babel import lazy_gettext as N_

from cps import hardcover_state_sync, logger, ub
from cps.services.worker import CalibreTask


class TaskHardcoverStateSync(CalibreTask):
    def __init__(self, user_id, task_message=N_('Hardcover state sync'), source="scheduled"):
        super(TaskHardcoverStateSync, self).__init__(task_message)
        self.log = logger.create()
        self.user_id = user_id
        self.source = source
        self.progress = 0

    @property
    def name(self):
        return N_("Hardcover State Sync")

    @property
    def is_cancellable(self):
        return False

    def run(self, worker_thread):
        try:
            user = ub.session.query(ub.User).filter(ub.User.id == int(self.user_id)).first()
            if not user:
                self._handleError(f"User {self.user_id} not found")
                return
            self.progress = 0.2
            result = hardcover_state_sync.sync_user(user, source=self.source or "scheduled")
            self.progress = 1.0
            if result.get("errors"):
                self._handleError("; ".join(result.get("errors")))
            else:
                self._handleSuccess()
        except Exception as e:
            self.log.error("Hardcover state sync task failed for user %s: %s", self.user_id, e)
            self._handleError(str(e))
