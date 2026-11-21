"""Point-in-time (retrospective) editions of the cycle monitor.

A retrospective edition re-runs the CycleAnalyzer models on the information
set that existed *before* the edition's cutoff (00:00 Europe/Warsaw on the
edition Sunday). Every statistical history comes from an explicit vintage or
an immutable pre-cutoff archive:

  REER, 10y yields, US CPI   ALFRED vintages (Friday before the cutoff)
  OECD CLI                   DBnomics OECD fetcher git commit (DSD_KEI@DF_KEI)
  business confidence        DBnomics OECD git commit (DSD_STES@DF_BTS),
                             percent-balance normalized on pre-cutoff history
  CPI y/y                    DBnomics BIS / OECD git commits (best pre-cutoff)
  policy rates               DBnomics BIS WS_CBPOL git commit (monthly + daily);
                             decisions after the archive date only when
                             announced *and* effective before the cutoff

The present-day repository cache (``data/raw``) is never an input.
"""
