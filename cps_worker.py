#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import sys


path = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, path)

from cps.worker_main import main


if __name__ == '__main__':
    main()
