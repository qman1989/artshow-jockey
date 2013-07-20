# Artshow Jockey
# Copyright (C) 2009, 2010 Chris Cogdon
# See file COPYING for licence details

from django.shortcuts import render
from django.db.models import Sum, Min
from django.http import HttpResponse
from django import forms
from django.core.context_processors import csrf
from django.contrib.auth.decorators import permission_required

from artshow.models import *


@permission_required('artshow.is_artshow_staff')
def index(request):
    return render(request, 'artshow/reports.html')


@permission_required('artshow.is_artshow_staff')
def artists(request):
    query = request.GET.get('q','all')
    artists = Artist.objects.annotate(requested=Sum("allocation__requested"),
                                      allocated=Sum("allocation__allocated")).order_by('artistid')
    return render(request, 'artshow/reports-artists.html', {'artists': artists, 'query': query})


@permission_required('artshow.is_artshow_staff')
def winning_bidders(request):
    bidders = Bidder.objects.all().annotate(first_bidderid=Min('bidderid')).order_by('first_bidderid')
    return render(request, 'artshow/reports-winning-bidders.html', {'bidders': bidders})


@permission_required('artshow.is_artshow_staff')
def artist_piece_report(request, artist_id):
    artist = Artist.objects.get(id=artist_id)
    pieces = artist.piece_set.all()
    return render(request, 'artshow/artist-piece-report.html', {'artist': artist, 'pieces': pieces})


@permission_required('artshow.is_artshow_staff')
def artist_panel_report(request):
    artists = Artist.objects.all()
    return render(request, 'artshow/artist-panel-report.html', {'artists': artists})


@permission_required('artshow.is_artshow_staff')
def panel_artist_report(request):
    locations = Piece.objects.exclude(location="").values("location").distinct()
    for l in locations:
        l['artists'] = Artist.objects.filter(piece__location=l['location']).distinct()
    return render(request, "artshow/panel-artist-report.html", {'locations': locations})


@permission_required('artshow.is_artshow_staff')
def artist_payment_report(request):
    non_zero = request.GET.get('nonzero', '1') == '1'
    artists = Artist.objects.annotate(total=Sum('payment__amount')).order_by("artistid")
    if non_zero:
        artists = artists.exclude(total=0)
    return render(request, 'artshow/artist-payment-report.html', {'artists': artists, 'non_zero':non_zero})


@permission_required('artshow.is_artshow_staff')
def show_summary(request):
    pieces = Piece.objects.all()

    class Stats:
        pieces_entered = 0
        pieces_showing = 0
        bids = 0
        pieces_va = 0
        bidamt = 0
        bidamt_va = 0
        highest_amt = 0
        highest_amt_va = 0
        highest_amt_sa = 0

    all_stats = Stats()
    general_stats = Stats()
    adult_stats = Stats()

    for p in pieces:
        section_stats = adult_stats if p.adult else general_stats
        all_stats.pieces_entered += 1
        section_stats.pieces_entered += 1
        # TODO we might need to cover other cases here
        if p.status != p.StatusNotInShow:
            all_stats.pieces_showing += 1
            section_stats.pieces_showing += 1
        try:
            top_bid = p.top_bid()
            all_stats.bids += 1
            section_stats.bids += 1
            all_stats.bidamt += top_bid.amount
            section_stats.bidamt += top_bid.amount
            all_stats.highest_amt = max(all_stats.highest_amt, top_bid.amount)
            section_stats.highest_amt = max(section_stats.highest_amt, top_bid.amount)
            if p.voice_auction:
                all_stats.pieces_va += 1
                section_stats.pieces_va += 1
                all_stats.bidamt_va += top_bid.amount
                section_stats.bidamt_va += top_bid.amount
                all_stats.highest_amt_va = max(all_stats.highest_amt_va, top_bid.amount)
                section_stats.highest_amt_va = max(section_stats.highest_amt_va, top_bid.amount)
            else:
                all_stats.highest_amt_sa = max(all_stats.highest_amt_sa, top_bid.amount)
                section_stats.highest_amt_sa = max(section_stats.highest_amt_sa, top_bid.amount)
        except Bid.DoesNotExist:
            pass

    artists = Artist.objects.all()
    num_artists = num_showing_artists = num_active_artists = 0
    for a in artists:
        num_artists += 1
        if a.is_showing():
            num_showing_artists += 1
        if a.is_active():
            num_active_artists += 1

    payment_types = PaymentType.objects.annotate(total_payments=Sum('payment__amount'))
    total_payments = sum([(pt.total_payments or Decimal("0.0")) for pt in payment_types])

    tax_paid = Invoice.objects.aggregate(tax_paid=Sum('tax_paid'))['tax_paid'] or Decimal(0)
    piece_charges = InvoiceItem.objects.aggregate(piece_charges=Sum('price'))['piece_charges'] or Decimal(0)
    total_charges = tax_paid + piece_charges

    invoice_payments = InvoicePayment.objects.values('payment_method').annotate(total=Sum('amount'))
    payment_method_choice_dict = dict(InvoicePayment.PAYMENT_METHOD_CHOICES)
    for ip in invoice_payments:
        ip['payment_method_desc'] = payment_method_choice_dict[ip['payment_method']]
    total_invoice_payments = InvoicePayment.objects.aggregate(total=Sum('amount'))['total'] or Decimal(0)

    spaces = Space.objects.annotate(requested=Sum('allocation__requested'), allocated2=Sum('allocation__allocated'))
    for s in spaces:
        s.requested_perc = s.requested/s.available*100 if s.requested is not None and s.available>0 else 0
        s.allocated_perc = s.allocated2/s.available*100 if s.allocated2 is not None and s.available>0 else 0

    # all_invoices = Invoice.objects.aggregate ( Sum('tax_paid'), Sum('invoicepayment__amount') )

    return render(request, 'artshow/show-summary.html',
                  {'all_stats': all_stats, 'general_stats': general_stats, 'adult_stats': adult_stats,
                   'num_showing_artists': num_showing_artists, 'payment_types': payment_types,
                   'total_payments': total_payments, 'tax_paid': tax_paid, 'piece_charges': piece_charges,
                   'total_charges': total_charges, 'total_invoice_payments': total_invoice_payments,
                   'invoice_payments': invoice_payments, 'spaces':spaces, 'num_artists':num_artists,
                   'num_active_artists': num_active_artists})


@permission_required('artshow.is_artshow_staff')
def voice_auction(request):
    adult = request.GET.get('adult', '')
    if adult not in ['y','n']:
        adult = ''

    pieces = Piece.objects.exclude(status=Piece.StatusNotInShow).filter(voice_auction=True).order_by("order", "artist",
                                                                                                     "pieceid")
    if adult == "y":
        pieces = pieces.filter(adult=True)
    elif adult == "n":
        pieces = pieces.filter(adult=False)

    return render(request, 'artshow/voice-auction.html', {'pieces': pieces, 'adult': adult})


@permission_required('artshow.is_artshow_staff')
def sales_percentiles(request):
    groups = int(request.GET.get('groups', '20'))

    amounts = []
    perc_amounts = []
    pieces = Piece.objects.exclude(status=Piece.StatusNotInShow)
    for p in pieces:
        try:
            tb = p.top_bid()
            amounts.append(tb.amount)
        except Bid.DoesNotExist:
            pass

    if amounts:
        amounts.sort()
        num_amounts = len(amounts)
        groups = min(groups, num_amounts)

        for i in range(1, groups):
            j = float(i) * num_amounts / groups
            j_before = int(j)
            j_after = j_before + 1
            amount = float(amounts[j_before]) * (j_after - j) + float(amounts[j_after]) * (j - j_before)
            perc_amounts.append({'perc': float(i) / groups, 'amount': amount})
        perc_amounts.append({'perc': 1.0, 'amount': float(amounts[-1])})

    return render(request, 'artshow/sales-percentiles.html', {'perc_amounts': perc_amounts})
