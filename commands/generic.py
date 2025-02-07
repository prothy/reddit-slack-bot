import collections
import ctypes
import datetime
import json
import math
import os
import random
import re
import subprocess

import click
import humanfriendly
import psutil
import requests

from commands import gyrobot, DefaultCommandGroup, chat, logger
from state_file import state_file

_ntuple_diskusage = collections.namedtuple('usage', 'total used free')


@gyrobot.command('binary', aliases=['b'],
                 context_settings={
                     'ignore_unknown_options': True,
                     'allow_extra_args': True}
                 )
@click.pass_context
def binary(ctx):
    """Convert binary to text"""
    rest_of_text = ' '.join(ctx.args)
    rest_of_text = re.sub(r'(\S{8})\s?', r'\1 ', rest_of_text)
    decoded_text = ''.join([chr(int(c, 2)) for c in rest_of_text.split()])
    chat(ctx).send_text(''.join(decoded_text))


@gyrobot.command('cointoss')
@click.pass_context
def cointoss(ctx):
    """Toss a coin"""
    toss = random.randrange(2)
    toss_text = ['Heads', 'Tails'][toss]
    chat(ctx).send_text(toss_text)


@gyrobot.command('convert')
@click.argument('value_text', type=click.FLOAT, metavar="«value»")
@click.argument('currency_from', type=click.STRING, metavar="«currency from»")
@click.argument('_literal_to', type=click.UNPROCESSED, metavar='"TO"')
@click.argument('currency_to', type=click.STRING, metavar="«currency to»")
@click.pass_context
def convert(ctx, value_text, currency_from, _literal_to, currency_to):
    """Convert money from one currency to another.

    Example: convert 100.0 USD TO EUR"""

    try:
        value = float(value_text)
    except ValueError:
        chat(ctx).send_text(f"{value_text} is not a good number", is_error=True)
        return

    if not (re.match(r'^\w+$', currency_from)):
        chat(ctx).send_text(f"{currency_from} is not a real currency", is_error=True)
        return

    if not (re.match(r'^\w+$', currency_to)):
        chat(ctx).send_text(f"{currency_to} is not a real currency", is_error=True)
        return

    currency_from = currency_from.upper()
    currency_to = currency_to.upper()

    if currency_from == currency_to:
        chat(ctx).send_text("Tautological bot is tautological", is_error=True)
        return

    prices_page = requests.get("https://min-api.cryptocompare.com/data/price",
                               params={'fsym': currency_from, 'tsyms': currency_to})
    logger(ctx).info(prices_page.url)
    prices = prices_page.json()
    if prices.get('Response') == 'Error':
        text = prices['Message']
    else:
        price = prices[currency_to]
        new_value = value * price
        text = f"{value:.2f} {currency_from} is {new_value:.2f} {currency_to}"
    chat(ctx).send_text(text)


def _lookup_country(country):
    country = country.lower()
    country = {'uk': 'gb'}.get(country, country)
    with open('countries.json') as f:
        country_lookup = json.load(f)
    # if country == 'usa': search_country = 'us'

    found_countries = [c for c in country_lookup
                       if country == c['name']['common'].lower()
                       or country == c['name']['official'].lower()
                       or any([country == names['common'].lower() for lang, names in c['name']['native'].items()])
                       or any([country == names['official'].lower() for lang, names in c['name']['native'].items()])
                       or country == c['cca2'].lower()
                       or country == c['cca3'].lower()
                       or country == c['cioc'].lower()]
    result = found_countries[0] if len(found_countries) > 0 else None
    return result


@gyrobot.command('covid', aliases=['covid19', 'covid_19'],
                 context_settings={
                     'ignore_unknown_options': True,
                     'allow_extra_args': True})
@click.argument('country', type=click.STRING)
@click.pass_context
def covid(ctx, country: str):
    """Display last available statistics for COVID-19 cases

    Syntax:

    covid19 GR
    covid19 GRC
    covid19 Greece
    covid19 Ελλάδα"""
    if country == '19' and len(ctx.args):
        country = ctx.args.pop(0)
    if len(ctx.args) > 0:
        country += ' ' + ' '.join(ctx.args)
    country_info = _lookup_country(country.lower())
    if not country_info:
        chat(ctx).send_text(f"Country \"{country}\" not found", is_error=True)
        return
    country = country_info['cca3'].upper()

    with open('data/owid-covid-data.json') as f:
        full_data = json.load(f)
        if type(full_data) is str:
            full_data = json.loads(full_data)
    country_data = full_data[country]
    data = {}
    relevant_data = list(filter(lambda d: ('new_cases' in d and 'new_deaths' in d), country_data['data']))
    for data_for_day in relevant_data[-7:-1]:
        data |= data_for_day
        if 'new_vaccinations' or 'total_vaccinations' in data_for_day:
            data['vaccinations_on'] = data_for_day['date']

    report_date = datetime.datetime.strptime(data['date'], '%Y-%m-%d')

    new_cases = data.get('new_cases', 0.0)
    new_deaths = data.get('new_deaths', 0.0)
    new_vaccinations = data.get('new_vaccinations', 0.0)
    total_vaccinations = data.get('total_vaccinations', 0.0)
    vaccinations_percent = data.get('total_vaccinations_per_hundred', 0.0)
    vaccinations_on = datetime.datetime.strptime(data['vaccinations_on'], '%Y-%m-%d')
    chat(ctx).send_text((f"*Date*: {report_date:%h %d %Y}\n"
                         f"*New Cases*: {new_cases:.10n}\n"
                         f"*Deaths*: {new_deaths:.10n}\n"
                         f"*Vaccinations*: {new_vaccinations:.10n}/{total_vaccinations:.10n} "
                         f"({vaccinations_percent:.5n}%) - on {vaccinations_on:%h %d %Y}"))


@gyrobot.command('crypto')
@click.argument('symbol', nargs=-1)
@click.pass_context
def crypto(ctx, symbol):
    """Display the current exchange rate of currency"""
    for cryptocoin in symbol:
        cryptocoin = cryptocoin.upper()
        prices = requests.get("https://min-api.cryptocompare.com/data/price",
                              params={'fsym': cryptocoin, 'tsyms': 'USD,EUR'}).json()
        if prices.get('Response') == 'Error':
            chat(ctx).send_text('```' + prices['Message'] + '```\n', is_error=True)
        else:
            chat(ctx).send_text(f"{cryptocoin} price is € {prices['EUR']} or $ {prices['USD']}")


def _diskfree():
    du = _disk_usage_raw('/')
    du_text = _disk_usage_human()
    return _progress_bar(du.used / du.total, 48) + '\n```\n' + du_text + '\n```\n'


if hasattr(os, 'statvfs'):  # POSIX
    def _disk_usage_raw(path):
        st = os.statvfs(path)
        free = st.f_bavail * st.f_frsize
        total = st.f_blocks * st.f_frsize
        used = (st.f_blocks - st.f_bfree) * st.f_frsize
        return _ntuple_diskusage(total, used, free)


    def _disk_usage_human():
        disk_usage_command = [
            'df',
            '--total',
            '--exclude-type=tmpfs',
            '--exclude-type=devtmpfs',
            '--exclude-type=squashfs',
            '--human-readable']
        return subprocess.check_output(disk_usage_command).decode()

elif os.name == 'nt':  # Windows
    def _disk_usage_raw(path):
        _, total, free = ctypes.c_ulonglong(), ctypes.c_ulonglong(), \
                         ctypes.c_ulonglong()
        fun = ctypes.windll.kernel32.GetDiskFreeSpaceExW
        ret = fun(path, ctypes.byref(_), ctypes.byref(total), ctypes.byref(free))
        if ret == 0:
            raise ctypes.WinError()
        used = total.value - free.value
        return _ntuple_diskusage(total.value, used, free.value)


    def _disk_usage_human():
        disk_usage_command = ['wmic', 'LogicalDisk', 'Where DriveType="3"', 'Get', 'DeviceID,FreeSpace,Size']
        return subprocess.check_output(disk_usage_command).decode()


def _progress_bar(percentage, size):
    filled = math.ceil(size * percentage)
    empty = math.floor(size * (1 - percentage))
    bar = '\u2588' * filled + '\u2591' * empty
    return bar


@gyrobot.command('disk_space')
@click.pass_context
def disk_space(ctx):
    """\
    Display free disk space"""
    chat(ctx).send_text(_diskfree())


@gyrobot.command('disk_space_ex')
@click.pass_context
def disk_space_ex(ctx):
    """Display free disk space"""
    chat(ctx).send_text('```' + subprocess.check_output(
        ['duf',
         '-only', 'local',
         '-output', 'mountpoint,size,avail,usage',
         '-style', 'unicode',
         '-width', '120']).decode() + '```')


@gyrobot.command('fortune')
@click.pass_context
def fortune(ctx):
    """Like a Chinese fortune cookie, but less yummy"""
    chat(ctx).send_text(subprocess.check_output(['/usr/games/fortune']).decode())


@gyrobot.command('joke')
@click.pass_context
def joke(ctx):
    """Tell a joke"""
    joke_page = requests.get('https://icanhazdadjoke.com/', headers={
        'Accept': 'text/plain',
        'User-Agent': 'Slack Bot for Reddit (https://github.com/gschizas/slack-bot)'})
    joke_text = joke_page.content
    chat(ctx).send_text(joke_text.decode())


MAGIC_8_BALL_OUTCOMES = [
    "It is certain.",
    "It is decidedly so.",
    "Without a doubt.",
    "Yes - definitely.",
    "You may rely on it.",
    "As I see it, yes.",
    "Most likely.",
    "Outlook good.",
    "Yes.",
    "Signs point to yes.",
    "Reply hazy, try again.",
    "Ask again later.",
    "Better not tell you now.",
    "Cannot predict now.",
    "Concentrate and ask again.",
    "Don't count on it.",
    "My reply is no.",
    "My sources say no.",
    "Outlook not so good.",
    "Very doubtful."]
DICE_REGEX = r'^(?P<Times>\d{1,2})?d(?P<Sides>\d{1,2})\s*(?:\+\s*(?P<Bonus>\d{1,2}))?$'


@gyrobot.group('roll', cls=DefaultCommandGroup)
def roll():
    """Roll a dice. Optional sides argument (e.g. roll 1d20+5, roll 1d6+2, d20 etc.)"""
    pass


@roll.command(default_command=True,
              context_settings={
                  'ignore_unknown_options': True,
                  'allow_extra_args': True})
@click.argument('specs', nargs=-1, required=False)
@click.pass_context
def roll_default(ctx, specs=None):
    """Roll a dice. Optional sides argument (e.g. roll 1d20+5, roll 1d6+2, d20 etc.)"""
    if specs is None:
        specs = ['1d6+0']

    for spec in specs:
        dice_spec = re.match(DICE_REGEX, spec)
        sides = times = bonus = 0
        if dice_spec:
            if dice_spec.group('Times'):
                times = int(dice_spec.group('Times'))
            if dice_spec.group('Bonus'):
                bonus = int(dice_spec.group('Bonus'))
            if dice_spec.group('Sides'):
                sides = int(dice_spec.group('Sides'))
        if sides < 2: sides = 6
        if times < 1: times = 1
        rolls = []
        for roll_index in range(times):
            rolls.append(random.randint(1, sides))
        final_roll = sum(rolls) + bonus
        roll_text = ', '.join(map(str, rolls))
        times_text = 'time' if times == 1 else 'times'
        chat(ctx).send_text((
            f"You rolled a {sides}-sided dice {times} {times_text} with a bonus of +{bonus}."
            f" You got {roll_text}. Final roll: *{final_roll}*"))


@roll.command('magic8')
@click.pass_context
def roll_magic8(ctx):
    result = random.choice(MAGIC_8_BALL_OUTCOMES)
    chat(ctx).send_text(result)


@roll.command('statline')
@click.argument('spec', nargs=1, required=False)
@click.pass_context
def roll_statline(ctx, spec=None):
    min_roll = 2 if spec == 'drop1' else 1
    ability_text = ""
    for roll_line in range(6):
        ability_line = []
        for roll_dice in range(4):
            dice = random.randint(min_roll, 6)
            ability_line.append(dice)
        ability_line_sorted = sorted(ability_line)[1:]
        ability_text += (
            f"You rolled 4d6: {', '.join([str(a) for a in ability_line])}."
            f" Keeping {', '.join([str(a) for a in ability_line_sorted])},"
            f" for a sum of *{sum(ability_line_sorted)}*.\n")
    chat(ctx).send_text(ability_text)


MID_DOT: str = '\xb7'


@gyrobot.command('stocks', aliases=['stock', 'stonk'])
@click.argument("stock_name")
@click.pass_context
def stocks(ctx, stock_name):
    """Show info for a stock"""
    import yfinance as yf

    if '|' in stock_name:
        stock_name = re.findall(r'\|(.*)>', stock_name)[0]
    stock_name = stock_name.replace(MID_DOT, '.')
    stock = yf.Ticker(stock_name)

    change = (((stock.info['ask'] / stock.info['previousClose']) - 1) * 100)  # > 10

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{stock.info['longName']} ({stock.info['symbol'].replace('.', MID_DOT)}) " +
                        f"{stock.info['currency']}"
            },
            "accessory": {
                "type": "image",
                "image_url": stock.info['logo_url'],
                "alt_text": stock.info['longName']
            },
            "fields": [
                {
                    "type": "plain_text",
                    "text": f"Ask Price: {stock.info['ask']}"
                },
                {
                    "type": "plain_text",
                    "text": f"Bid: {stock.info['bid']}"
                },
                {
                    "type": "plain_text",
                    "text": f"Low: {stock.info['regularMarketDayLow']}"
                },
                {
                    "type": "plain_text",
                    "text": f"Day High: {stock.info['dayHigh']}"
                },
                {
                    "type": "plain_text",
                    "text": f"Last Day: {stock.info['regularMarketPreviousClose']}"
                },
                {
                    "type": "plain_text",
                    "text": f"Change: {change:.02f}"
                }
            ]
        }
    ]
    chat(ctx).send_blocks(blocks)


@gyrobot.command('uptime')
@click.pass_context
def uptime(ctx):
    """Show uptime"""
    now = datetime.datetime.now()
    server_uptime = now - datetime.datetime.fromtimestamp(psutil.boot_time())
    process_uptime = now - datetime.datetime.fromtimestamp(psutil.Process(os.getpid()).create_time())
    chat(ctx).send_text((f"Server uptime: {humanfriendly.format_timespan(server_uptime)}\n"
                         f"Process uptime: {humanfriendly.format_timespan(process_uptime)}"))


@gyrobot.command('urban_dictionary', aliases=['ud'])
@click.argument('terms', nargs=-1)
@click.pass_context
def urban_dictionary(ctx, terms):
    """Search in urban dictionary for the first definition of the word or phrase"""
    term = ' '.join(terms)
    definition_page = requests.get('http://api.urbandictionary.com/v0/define', params={'term': term})
    definition_answer = definition_page.json()
    if len(definition_answer) > 0:
        chat(ctx).send_text(definition_answer['list'][0]['definition'])
    else:
        chat(ctx).send_text(f"Could not find anything for {term}", is_error=True)


@gyrobot.command('weather', aliases=['w'])
@click.argument("place", nargs=-1, required=False)
@click.pass_context
def weather(ctx, place):
    """Display the weather in any place.

    Syntax: weather PLACE

    if PLACE is skipped, the location from the last query is used.
    """
    place_full = ' '.join(place)

    with state_file('weather') as pref_cache:
        if place_full:
            pref_cache[chat(ctx).user_id] = place_full
        else:
            place_full = pref_cache.get(chat(ctx).user_id, '')

    if place_full == 'macedonia' or place_full == 'makedonia':
        place_full = 'Thessaloniki'
    if place_full == '':
        chat(ctx).send_text(
            ('You need to first set a default location\n'
             f'Try `{chat(ctx).bot_name} weather LOCATION`'), is_error=True)
        return
    place_full = place_full.replace("?", "")
    if place_full in ('brexit', 'pompeii'):
        title = 'the floor is lava'
        with open('img/lava.png', 'rb') as f:
            file_data = f.read()
    else:
        weather_page = requests.get('http://wttr.in/' + place_full + '_p0.png?m')
        file_data = weather_page.content
        title = place_full
    chat(ctx).send_file(file_data, title=title, filetype='png')
