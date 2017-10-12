# -*- coding=utf-8 -*-
import os
import os.path
from app import app, redirect, render_template, request, get_locale, set_language_switch_link, g, serve_static_page, karp_query
from collections import defaultdict
from flask import jsonify, url_for
from flask_babel import gettext
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import Header
import helpers
import icu  # pip install PyICU
import json
import md5
from pylibmc import Client
import re
import smtplib
import urllib
from urllib2 import urlopen

client = Client(app.config['MEMCACHED'])


# redirect to specific language landing-page
@app.route('/')
def index():
    return redirect('/' + get_locale())


@app.route('/en', endpoint='index_en')
@app.route('/sv', endpoint='index_sv')
def start():
    rule = request.url_rule
    if 'sv' in rule.rule:
        infotext = u"""<p>Läs om 1 000 svenska kvinnor från medeltid till nutid.</p>
                       <p>Genom olika sökningar kan du se - vad de arbetade med,
                       vilken utbildning de fick, vilka organisationer de var med i,
                       hur de rörde sig i världen, vad de åstadkom och mycket mera.</p>
                       <p>Alla har de bidragit till samhällets utveckling.</p>"""
    else:
        infotext = u"""<p>Read up on 1000 Swedish women – from the middle ages to the present day.</p>
                       <p>Use the search function to reveal what these women got up to, how they were educated,
                       which organisations they belonged to, whether they travelled, what they achieved, and much more.</p>
                       <p>All of them contributed in a significant way to the development of Swedish society.</p>"""
    set_language_switch_link("index")
    return render_template('start.html', infotext=infotext)


@app.route("/en/about-skbl", endpoint="about-skbl_en")
@app.route("/sv/om-skbl", endpoint="about-skbl_sv")
def about_skbl():
    return serve_static_page("about-skbl", gettext("About SKBL"))


@app.route("/en/contact", endpoint="contact_en")
@app.route("/sv/kontakt", endpoint="contact_sv")
def contact():
    set_language_switch_link("contact")
    return render_template("contact.html",
                           title=gettext("Contact"),
                           headline=gettext("Contact SKBL"))


@app.route('/en/contact/', methods=['POST'], endpoint="submitted_en")
@app.route('/sv/kontakt/', methods=['POST'], endpoint="submitted_sv")
def submit_contact_form():
    set_language_switch_link("contact")
    name = request.form['name'].strip()
    email = request.form['email'].strip()
    message = request.form['message']

    errors = []
    if not name or not email or not message:
        errors.append(gettext("Please enter all the fields!"))
    if email and not helpers.is_email_address_valid(email):
        errors.append(gettext("Please enter a valid email address!"))

    # Render error messages and tell user what went wrong
    if errors:
        name_error = False if name else True
        email_error = False if email else True
        message_error = False if message else True
        return render_template("contact.html",
                               title=gettext("Contact"),
                               headline=gettext("Contact SKBL"),
                               errors=errors,
                               name_error=name_error,
                               email_error=email_error,
                               message_error=message_error,
                               name=name,
                               email=email,
                               message=message)

    # Compose and send email
    else:
        text = u"%s har skickat följande meddelande:\n\n%s" % (name, message)
        html = text.replace("\n", "<br>")
        part1 = MIMEText(text, "plain", "utf-8")
        part2 = MIMEText(html, "html", "utf-8")

        msg = MIMEMultipart("alternative")
        msg.attach(part1)
        msg.attach(part2)

        msg["Subject"] = u"Förfrågan från skbl.se"
        msg['To'] = app.config['EMAIL_RECIPIENT']

        # Work-around: things won't be as pretty if email adress contains non-ascii chars
        if helpers.is_ascii(email):
            msg['From'] = "%s <%s>" % (Header(name, 'utf-8'), email)
        else:
            msg['From'] = u"%s <%s>" % (name, email)
            email = ""

        server = smtplib.SMTP("localhost")
        server.sendmail(email, [app.config['EMAIL_RECIPIENT']], msg.as_string())
        server.quit()

        # Render user feedback
        return render_template("form_submitted.html",
                               title=gettext("Thank you for your feedback") + "!",
                               headline=gettext("Thank you for your feedback") + ", " + name + "!",
                               text=gettext("We will get back to you as soon as we can."))


@app.route("/en/search", endpoint="search_en")
@app.route("/sv/sok", endpoint="search_sv")
def search():
    set_language_switch_link("search")
    search = request.args.get('q', '*').encode('utf-8')
    karp_q = {}
    if '*' in search:
        search = re.sub('(?<!\.)\*', '.*', search)
        karp_q['q'] = "extended||and|anything|regexp|%s" % search
        karp_q['sort'] = '_score'
    else:
        karp_q['q'] = "extended||and|anything|contains|%s" % search

    data = karp_query('query', karp_q)
    advanced_search_text = ''
    with app.open_resource("static/pages/advanced-search/%s.html" % (g.language)) as f:
        advanced_search_text = f.read()

    return render_template('list.html', headline=gettext('Hits for "%s"') % search.decode("UTF-8"),
                           hits=data["hits"],
                           advanced_search_text=advanced_search_text.decode("UTF-8"),
                           search=search.decode("UTF-8"),
                           alphabetic=True)


@app.route("/en/place", endpoint="place_index_en")
@app.route("/sv/ort", endpoint="place_index_sv")
def place_index():

    set_language_switch_link("place_index")
    rv = client.get('place')
    if rv is not None and not app.config['TEST']:
        return rv

    rule = request.url_rule
    if 'sv' in rule.rule:
        infotext = u"""Här kan du se var de biograferade kvinnorna befunnit sig;
        var de fötts, verkat och dött. Genom att klicka på en ord kan du se vilka som fötts,
        verkat och/eller avlidit där."""
    else:
        infotext = u"""This displays the subjects’ locations: where they were born
        where they were active, and where they died. Selecting a particular placename
        generates a list of all subjects who were born, active and/or died at that place."""

    def parse(kw):
        place = kw.get('key')
        name, lat, lon = place.split('|')
        placename = name if name else '%s, %s' % (lat, lon)
        lat = place.split('|')[1]
        lon = place.split('|')[2]
        return {'name': placename, 'lat': lat, 'lon': lon,
                'count': kw.get('doc_count')}

    def has_name(kw):
        name = kw.get('key').split('|')[0]
        if name and u"(osäker uppgift)" not in name:
            return name
        else:
            return None

    data = karp_query('getplaces', {})
    stat_table = [parse(kw) for kw in data['places'] if has_name(kw)]
    # Sort and translate
    # stat_table = helpers.sort_places(stat_table, request.url_rule)
    collator = icu.Collator.createInstance(icu.Locale('sv_SE.UTF-8'))
    stat_table.sort(key=lambda x: collator.getSortKey(x.get('name').strip()))
    art = render_template('places.html', places=stat_table, title=gettext("Placenames", infotext=infotext))
    client.set('place', art, time=app.config['CACHE_TIME'])
    return art


@app.route("/en/place/<place>", endpoint="place_en")
@app.route("/sv/ort/<place>", endpoint="place_sv")
def place(place=None):
    lat = request.args.get('lat')
    lon = request.args.get('lon')
    set_language_switch_link("place_index", place)
    hits = karp_query('querycount', {'q': "extended||and|plats.search|equals|%s" % (place.encode('utf-8'))})
    if hits['query']['hits']['total'] > 0:
        return render_template('placelist.html', title=place, lat=lat, lon=lon,
                               headline=place, hits=hits["query"]["hits"])
    else:
        return render_template('page.html', content='not found')


@app.route("/en/organisation", endpoint="organisation_index_en")
@app.route("/sv/organisation", endpoint="organisation_index_sv")
def organisation_index():
    set_language_switch_link("organisation_index")
    if client.get('organisation') is not None and not app.config['TEST']:
        return client['organisation']

    rule = request.url_rule
    if 'sv' in rule.rule:
        infotext = u"""Här kan du se vilka organisationer de biograferade kvinnorna varit medlemmar
        och verksamma i. Det ger en inblick i de nätverk som var de olika kvinnornas och visar
        såväl det gemensamma engagemanget som mångfalden i det.
        Om du klickar på organisationens namn visas vilka kvinnor som var aktiva i den."""
    else:
        infotext = u"""This displays the organisations which the subjects in the dictionary joined
        and within which they were active. This not only provides an insight into each woman’s
        networks but also highlights both shared activities and their diversity.
        Selecting a particular organisation generates a list of all women who were members."""

    data = karp_query('minientry', {'q': 'extended||and|anything|regexp|.*',
                                    'show': 'organisationsnamn,organisationstyp'})
    nested_obj = {}
    for hit in data['hits']['hits']:
        for org in hit['_source'].get('organisation', []):
            orgtype = org.get('type', '-')
            if orgtype not in nested_obj:
                nested_obj[orgtype] = defaultdict(set)
            nested_obj[orgtype][org.get('name', '-')].add(hit['_id'])
    art = render_template('nestedbucketresults.html',
                          results=nested_obj, title=gettext("Organisations"),
                          infotext=infotext, name='organisation')
    client.set('organisation', art, time=app.config['CACHE_TIME'])
    return art
    # return bucketcall(queryfield='organisationstyp', name='organisation',
    #                   title='Organizations', infotext=infotext)


@app.route("/en/organisation/<result>", endpoint="organisation_en")
@app.route("/sv/organisation/<result>", endpoint="organisation_sv")
def organisation(result=None):
    title = request.args.get('title')
    return searchresult(result, 'organisation', 'id', 'organisations', title=title)


@app.route("/en/activity", endpoint="activity_index_en")
@app.route("/sv/verksamhet", endpoint="activity_index_sv")
def activity_index():
    set_language_switch_link("activity_index")
    if client.get('activity') is not None and not app.config['TEST']:
        return client['activity']
    rule = request.url_rule
    if 'sv' in rule.rule:
        infotext = u"Här kan du se inom vilka områden de biograferade kvinnorna varit verksamma och vilka yrken de hade."
    else:
        infotext = u"This displays the areas within which the biographical subject was active and which activities and occupation(s) they engaged in."
    art = bucketcall(queryfield='verksamhetstext', name='activity',
                     title=gettext("Activities"), infotext=infotext,
                     alphabetical=True)
    client.set('activity', art, time=app.config['CACHE_TIME'])
    return art


@app.route("/en/activity/<result>", endpoint="activity_en")
@app.route("/sv/verksamhet/<result>", endpoint="activity_sv")
def activity(result=None):
    return searchresult(result, name='activity', searchfield='verksamhetstext',
                        imagefolder='activities', title=result)


@app.route("/en/keyword", endpoint="keyword_index_en")
@app.route("/sv/nyckelord", endpoint="keyword_index_sv")
def keyword_index():
    rule = request.url_rule
    if 'sv' in rule.rule:
        infotext = u"""Här finns en lista över de nyckelord som karakteriserar materialet.
        De handlar om tid, yrken, ideologier och mycket mera.
        Om du klickar på något av nyckelorden kan du se vilka kvinnor som kan karakteriseras med det."""
    else:
        infotext = u"""This generates a list of keywords which typically appear in the entries.
        These include time periods, occupations, ideologies and much more.
        Selecting a keyword generates a list of all the women who fall under the given category."""
    return bucketcall(queryfield='nyckelord', name='keyword', title='Keywords', infotext=infotext)


@app.route("/en/keyword/<result>", endpoint="keyword_en")
@app.route("/sv/nyckelord/<result>", endpoint="keyword_sv")
def keyword(result=None):
    return searchresult(result, 'keyword', 'nyckelord', 'keywords')


@app.route("/en/articleauthor", endpoint="articleauthor_index_en")
@app.route("/sv/artikelforfattare", endpoint="articleauthor_index_sv")
def authors():
    rule = request.url_rule
    if 'sv' in rule.rule:
        infotext = u"""Här förtecknas de personer som har bidragit med artiklar till Svenskt kvinnobiografiskt lexikon. """
    else:
        infotext = u"""This is a list of the authors who supplied articles to SKBL."""
    return bucketcall(queryfield='artikel_forfattare_fornamn.bucket,artikel_forfattare_efternamn',
                      name='articleauthor', title='Article authors', sortby=lambda x: x[1],
                      lastnamefirst=True, infotext=infotext)


@app.route("/en/articleauthor/<result>", endpoint="articleauthor_en")
@app.route("/sv/artikelforfattare/<result>", endpoint="articleauthor_sv")
def author(result=None):
    return searchresult(result, name='articleauthor',
                        searchfield='artikel_forfattare_fulltnamn',
                        imagefolder='authors', searchtype='contains')


def searchresult(result, name='', searchfield='', imagefolder='', searchtype='equals', title=''):
    qresult = result
    try:
        set_language_switch_link("%s_index" % name, result)
        qresult = result.encode('utf-8')
        hits = karp_query('querycount', {'q': "extended||and|%s.search|%s|%s" % (searchfield, searchtype, qresult)})
        title = title or result

        if hits['query']['hits']['total'] > 0:
            picture = None
            if os.path.exists(app.config.root_path + '/static/images/%s/%s.jpg' % (imagefolder, qresult)):
                picture = '/static/images/%s/%s.jpg' % (imagefolder, qresult)

            return render_template('list.html', picture=picture, alphabetic=True,
                                   title=title, headline=title, hits=hits["query"]["hits"])
        else:
            return render_template('page.html', content='not found')
    except Exception:
        return render_template('page.html', content="%s: extended||and|%s.search|%s|%s" % (app.config['KARP_BACKEND'], searchfield, searchtype, qresult))


def bucketcall(queryfield='', name='', title='', sortby='', lastnamefirst=False,
               infotext='', query='', alphabetical=False):
    q_data = {'buckets': '%s.bucket' % queryfield}
    if query:
        q_data['q'] = query
    data = karp_query('statlist', q_data)
    # strip kw0 to get correct sorting
    stat_table = [[kw[0].strip()]+kw[1:] for kw in data['stat_table'] if kw[0] != ""]
    if sortby:
        stat_table.sort(key=sortby)
    else:
        stat_table.sort()
    if lastnamefirst:
        stat_table = [[kw[1] + ',', kw[0], kw[2]] for kw in stat_table]
    set_language_switch_link("%s_index" % name)
    return render_template('bucketresults.html', results=stat_table,
                           alphabetical=alphabetical, title=gettext(title),
                           name=name, infotext=infotext)


# def nestedbucketcall(queryfield=[], paths=[], name='', title='', sortby='', lastnamefirst=False):
#     data = karp_query('minientry', {'size': 1000,
#                                 'q': 'exentded||and|anything|regexp|.*',
#                                 'show': ','.join(queryfield)})
#     stat_table = data['aggregations']['q_statistics']
#     set_language_switch_link("%s_index" % name)
#     return render_template('nestedbucketresults.html', paths=paths,
#                            results=stat_table, title=gettext(title), name=name)


@app.route("/en/article", endpoint="article_index_en")
@app.route("/sv/artikel", endpoint="article_index_sv")
def article_index(search=None):
    # search is only used by links in article text

    set_language_switch_link("article_index")
    search = search or request.args.get('search')
    if search is not None:
        search = search.encode("UTF-8")
        data, id = find_link(search)
        if id:
            # only one hit is found, redirect to that page
            return redirect(url_for('article_'+g.language, id=id))
        elif data["query"]["hits"]["total"] > 1:
            # more than one hit is found, redirect to a listing
            return redirect(url_for('search_'+g.language, q=search))
        else:
            # no hits are found redirect to a 'not found' page
            return render_template('page.html', content='not found')

    if client.get('article') is not None and not app.config['TEST']:
        return client['article']
    data = karp_query('query', {'q': "extended||and|namn.search|exists"})
    infotext = u"""Klicka på namnet för att läsa biografin om den kvinna du vill veta mer om."""
    art = render_template('list.html',
                           hits=data["hits"],
                           headline=gettext(u'Women A-Ö'),
                           alphabetic=True,
                           split_letters=True,
                           infotext=infotext,
                           title='Articles')
    client.set('article', art, time=app.config['CACHE_TIME'])
    return art


@app.route("/en/article/<id>", endpoint="article_en")
@app.route("/sv/artikel/<id>", endpoint="article_sv")
def article(id=None):
    data = karp_query('querycount', {'q': "extended||and|id.search|equals|%s" % (id)})
    set_language_switch_link("article_index", id)
    return show_article(data)


def find_link(searchstring):
    # Finds an article based on ISNI or name
    if re.search('^[0-9 ]*$', searchstring):
        data = karp_query('querycount',
                          {'q': "extended||and|swoid.search|equals|%s" % (searchstring)})
    else:
        data = karp_query('querycount',
                          {'q': "extended||and|namn.search|contains|%s" % (searchstring)})
    # The expected case: only one hit is found
    if data['query']['hits']['total'] == 1:
        id = data['query']['hits']['hits'][0]['_id']
        return data, id
    # Otherwise just return the data
    else:
        return data, ''


def show_article(data):
    if data['query']['hits']['total'] == 1:
        # Malin: visa bara tilltalsnamnet (obs test, kanske inte är vad de vill ha på riktigt)
        source = data['query']['hits']['hits'][0]['_source']
        firstname, calling = helpers.get_first_name(source)
        # Print given name + lastname
        source['showname'] = "%s %s" % (calling, source['name'].get('lastname', ''))
        if source.get('text'):
            source['text'] = helpers.markdown_html(helpers.mk_links(source['text']))
        source['othernames'] = helpers.group_by_type(source.get('othernames', {}), 'name')
        source['othernames'].append({'type': u'Förnamn', 'name': firstname})
        helpers.collapse_kids(source)
        if "source" in source:
            source['source'] = helpers.aggregate_by_type(source['source'], use_markdown=True)
        if "furtherreference" in source:
            source['furtherreference'] = helpers.aggregate_by_type(source['furtherreference'], use_markdown=True)
        return render_template('article.html', article=source, article_id=id)
    else:
        return render_template('page.html', content='not found')

# @app.route("/en/article-find/<id>", endpoint="article_en")
# @app.route("/sv/artikel-find/<id>", endpoint="article_sv")
# def article(link=None):
#     if re.match('[0-9 ]', link):
#         data = karp_query('querycount', {'q': "extended||and|swoid.search|equals|%s" % (link)})
#         set_language_switch_link("article_index", link)
#         show_article(data)

@app.route("/en/award", endpoint="award_index_en")
@app.route("/sv/pris", endpoint="award_index_sv")
def award_index():
    # There are no links to this page, but might be wanted later on
    # Exists only to support award/<result> below
    return bucketcall(queryfield='prisbeskrivning', name='award', title='Award', infotext='')


@app.route("/en/award/<result>", endpoint="award_en")
@app.route("/sv/pris/<result>", endpoint="award_sv")
def award(result=None):
    return searchresult(result, name='award',
                        searchfield='prisbeskrivning',
                        imagefolder='award', searchtype='equals')


@app.route("/en/article/<id>.json", endpoint="article_json_en")
@app.route("/sv/artikel/<id>.json", endpoint="article_json_sv")
def article_json(id=None):
    data = karp_query('querycount', {'q': "extended||and|id.search|equals|%s" % (id)})
    if data['query']['hits']['total'] == 1:
        return jsonify(data['query']['hits']['hits'][0]['_source'])


@app.route('/emptycache')
def emptycache():
    # Users with write premissions to skbl may empty the cache
    emptied = False
    try:
        auth = request.authorization
        postdata = {}
        user, pw = auth.username, auth.password
        postdata["username"] = user
        postdata["password"] = pw
        postdata["checksum"] = md5.new(user + pw + app.config['SECRET_KEY']).hexdigest()
        server = app.config['WSAUTH_URL']
        contents = urlopen(server, urllib.urlencode(postdata)).read()
        auth_response = json.loads(contents)
        lexitems = auth_response.get("permitted_resources", {})
        rights = lexitems.get("lexica", {}).get(app.config['SKBL'], {})
        if rights.get('write'):
             client.flush_all()
             emptied = True
    except Exception as e:
        emptied = False
    return jsonify({"cached_emptied": emptied})


@app.route('/cachestats')
def cachestats():
    return jsonify({"cached_stats": client.get_stats()})
