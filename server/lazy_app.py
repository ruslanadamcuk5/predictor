# -*- coding: utf-8 -*-
"""Ленивая WSGI-обёртка для монтажа сервиса в чужой сайт.

Если сервис подключён к существующему Flask/Django-сайту через
``DispatcherMiddleware``, не хочется импортировать анализатор при старте
каждого worker: на бесплатном тарифе alwaysdata память ограничена. Эта
обёртка загружает ``app.wsgi`` при первом запросе к ``/predictor`` и
показывает понятную ошибку 503, если импорт не удался. Основной сайт при
этом продолжает работать.
"""

from __future__ import annotations

import importlib.util
import sys
import threading
import traceback
from importlib.machinery import SourceFileLoader


class LazyApplication(object):
    def __init__(self, path, name="predictor_wsgi"):
        self.path = path
        self.name = name
        self._lock = threading.Lock()
        self._app = None
        self._error = ""

    def _load(self):
        try:
            loader = SourceFileLoader(self.name, self.path)
            spec = importlib.util.spec_from_loader(self.name, loader)
            if spec is None or spec.loader is None:
                raise RuntimeError("не удалось загрузить %s" % self.path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[self.name] = module
            spec.loader.exec_module(module)
            app = getattr(module, "application", None)
            if app is None:
                raise RuntimeError("в %s нет application" % self.path)
            self._app = app
        except Exception:
            self._error = traceback.format_exc()
            try:
                sys.stderr.write("Betcity Predictor не загружен:\n" + self._error)
            except Exception:
                pass

    def __call__(self, environ, start_response):
        if self._app is None:
            with self._lock:
                if self._app is None and not self._error:
                    self._load()
        if self._app is None:
            body = "Betcity Predictor временно недоступен.".encode("utf-8")
            start_response("503 Service Unavailable", [
                ("Content-Type", "text/plain; charset=utf-8"),
                ("Content-Length", str(len(body))),
            ])
            return [body]
        return self._app(environ, start_response)
