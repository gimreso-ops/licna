"""
Provera u posebnom biračkom spisku – stranica se otvara unutar programa,
JMBG se upisuje automatski, operater samo prepisuje tekst sa slike (CAPTCHA).
Profil je "off-the-record": ništa se ne upisuje na disk (kolačići, keš, istorija).
"""
import json

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView

URL = "https://upit.posebanbirackispisak.gov.rs/"

JS_POPUNI = """
(function(jmbg){
  var ins = Array.from(document.querySelectorAll('input')).filter(function(i){
    var t = (i.type || 'text').toLowerCase();
    return (t === 'text' || t === 'number' || t === 'tel') && i.offsetParent !== null;
  });
  if (!ins.length) return 'nema';
  var j = ins.find(function(i){ return /jmbg/i.test((i.name||'') + (i.id||'')); }) || ins[0];
  j.value = jmbg;
  j.dispatchEvent(new Event('input', {bubbles:true}));
  j.dispatchEvent(new Event('change', {bubbles:true}));
  var c = ins.find(function(i){ return i !== j; });
  if (c) { c.value = ''; c.focus(); }
  return 'ok';
})(%s);
"""


class ProveraSpiska(QWebEngineView):
    def __init__(self, parent=None):
        super().__init__(parent)
        # bez imena = off-the-record; roditelj je aplikacija da bi profil nadživeo stranicu
        self._profil = QWebEngineProfile(QApplication.instance())
        self.setPage(QWebEnginePage(self._profil, self))
        self.jmbg = ""
        self.loadFinished.connect(self._ucitano)
        self.prazno()

    def prazno(self):
        self.jmbg = ""
        self.setHtml("<html><body style='font-family:Arial;color:#777;padding:30px'>"
                     "<h3>Provera u posebnom biračkom spisku</h3>"
                     "<p>Stranica će se otvoriti automatski posle očitavanja kartice.</p>"
                     "</body></html>")

    def proveri(self, jmbg):
        self.jmbg = jmbg
        self.load(QUrl(URL))

    def _ucitano(self, ok):
        if ok and self.jmbg and self.url().host() in QUrl(URL).host():
            self.page().runJavaScript(JS_POPUNI % json.dumps(self.jmbg))
            self.setFocus()
