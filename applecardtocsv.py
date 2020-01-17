#!/usr/bin/env python

__author__ = "Aki Korhonen"
__copyright__ = "Copyright 2019 Aki Korhonen"
__credits__ = ["Aki Korhonen"]
__license__ = "GPL"
__version__ = "1.0.1"
__maintainer__ = "Aki Korhonen"
__email__ = ""
__status__ = "Production"

"""
applecardtocsv.py:
Pipe Apple Card PDF statement to Mint-like CSV file for import to Quicken

Looks for matching PDF files in the folder that's specified as 
SCANFOLDER. Spits out CSV files that have "Import This" appended
to the file names.

Change pdfRePattern if you get statements in some other format.

This code assumes US date and currency formats, and USD for currency.

No guarantees that this thing works for any particular purpose.
"It seems to work on my computer"
"""

import os
import re
import subprocess
import tempfile
import atexit
import datetime
import csv


SCANFOLDER = '/Users/aki/Downloads'

pdfRePattern = re.compile(r"Apple Card Statement - (January|February|March|April|May|June|July|August|September|October|November|December) 20[12]\d.pdf")


P2TCMD = u"pdftotext"
TEMPDIR = tempfile.mkdtemp()
TEMP_TXT = os.path.join(TEMPDIR, "tmp.txt")
@atexit.register
def CleanupTempFile():
    if os.path.exists(TEMP_TXT):
        os.unlink(TEMP_TXT)
    os.rmdir(TEMPDIR)    

def readPdfFile(inf):

    if os.path.exists(TEMP_TXT):
        os.unlink(TEMP_TXT)
        
    c = subprocess.run([P2TCMD,"-layout", "-enc", "UTF-8", inf, TEMP_TXT],capture_output=True,encoding="UTF-8")
    if os.path.exists(TEMP_TXT):
        f = open(TEMP_TXT, encoding="UTF-8")
        r = f.readlines()
        f.close()
    else:
        r=[]
    
    return r



class AppleCardProcessor:
    OUT_FILE_POSTFIX = '_ImportThis.csv'
    PMT_RE=re.compile(r"(?P<date>\d\d/\d\d/20[12]\d) {5,}(?P<description>.+?) {5,}(?P<amount>-?\$?[0-9,]+\.\d\d)")
    TRX_RE=re.compile(r"(?P<date>\d\d/\d\d/20[12]\d) {5,}(?P<description>.+?) +(?P<dailycash>\d+[%] {1,30}-?\$?[0-9,]+\.\d\d) {5,}(?P<amount>-?\$?[0-9,]+\.\d\d)")
    DC_RE=re.compile(r"Total Daily Cash earned this month {5,}(?P<amount>-?\$?[0-9,]+\.\d\d)")
    SD_RE=re.compile(r"as of (?P<date>(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) +[0-3]\d, +20[1-2]\d)")
    SB_RE=re.compile(r"(?P<amount>-?\$?[0-9,]+\.\d\d)")
    IC_RE=re.compile(r"Total interest for this month +(?P<amount>-?\$?[0-9,]+\.\d\d)")

    def __init__(self,pdffile):
        self.pdffile = pdffile
        self.csvfile = pdffile[:-4]+self.OUT_FILE_POSTFIX
        self.statementdate = None
        self.statementbalance = None
        self.earliestdate = None
        self.lookforstatementbalancenext = False
        self.transactions = []
        self.SECTIONHANDLERS = {
            'Payments':self.PaymentLine,
            'Transactions':self.TransactionLine,
            'Interest Charged':self.InterestChargedLine,
            'Payment Information':self.PaymentInformationLine,
        }
        self.DEFAULTSECTION = "Payment Information"

    def PaymentLine(self,l):
        m = self.PMT_RE.match(l)
        if m:
            m = m.groupdict()
            d = datetime.datetime.strptime(m['date'], '%m/%d/%Y')
            a = float(m['amount'].replace("$","").replace(",",""))
            self.transactions.append((d,m['description'],a))

    def TransactionLine(self,l):
        m = self.TRX_RE.match(l)
        if m:
            m = m.groupdict()
            d = datetime.datetime.strptime(m['date'], '%m/%d/%Y')
            a = float(m['amount'].replace("$","").replace(",",""))
            self.transactions.append((d,m['description'],a))
        else:
            m = self.DC_RE.match(l)
            if m:
                a = float(m['amount'].replace("$","").replace(",",""))
                #self.transactions.append((self.statementdate,"Total Daily Cash earned this month", -1*a))
            
    def PaymentInformationLine(self,l):
        l = l.strip()
        
        if self.lookforstatementbalancenext:
            m = self.SB_RE.match(l)
            if m:
                m = m.groupdict()
                self.statementbalance = float(m['amount'].replace("$","").replace(",",""))
                self.lookforstatementbalancenext = False
            if "Minimum payment due" in l:
                self.lookforstatementbalancenext = False
                
        m = self.SD_RE.match(l)
        if m:
            m = m.groupdict()
            self.statementdate = datetime.datetime.strptime(m['date'], '%b %d, %Y')
            self.lookforstatementbalancenext = True

        
    def InterestChargedLine(self,l):
        l = l.strip()
        
        m = self.IC_RE.match(l)
        if m:
            m = m.groupdict()
            i = float(m['amount'].replace("$","").replace(",",""))
            if i!=0:
                self.transactions.append((self.statementdate, "Interest", i))


    def Read(self):
        t = readPdfFile(self.pdffile)
        
        sectiontype = self.DEFAULTSECTION
        
        for l in t:
            l = l.strip()
            
            if l.startswith(tuple(self.SECTIONHANDLERS.keys())):
                for i in self.SECTIONHANDLERS.keys():
                    if l.startswith(i):
                        sectiontype = i
                        break
                continue
            
            if sectiontype and self.SECTIONHANDLERS[sectiontype]:
                self.SECTIONHANDLERS[sectiontype](l)
                    
        if self.statementdate:
            self.earliestdate = self.statementdate.replace(day=1)
        
        for d,m,a in self.transactions:
            if d<self.earliestdate:
                self.earliestdate = d
        
    def Write(self):
        with open(self.csvfile, 'w') as c:
            spamwriter = csv.writer(c, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
            spamwriter.writerow('Date,Description,Original Description,Amount,Transaction Type,Category,Account Name,Labels,Notes'.split(','))
            
            for d,m,a in self.transactions:        
                a = -1 * a 
                trtype = a<0 and 'debit' or 'credit'
                amt = str(a)
                trdate = d.strftime('%m/%d/%Y')
                desc = m
                notes = m
                r = [
                    trdate,desc,'',amt,trtype,'','','',notes
                ]
                spamwriter.writerow(r)


toProcess = []

for f in os.listdir(SCANFOLDER):
    if pdfRePattern.match(f):
        toProcess.append(AppleCardProcessor(os.path.join(SCANFOLDER,f)))

for i in toProcess:
    i.Read()
    i.Write()
    

