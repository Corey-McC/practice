import sys
from bs4 import BeautifulSoup
import requests
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import re
import itertools
import time
import math


global DESIRED_CITY, SHEET_HEADER, MAX_LENGTH, LOOP_LENGTH_IN_MINUTES
DESIRED_CITY = 'pullman'
SHEET_HEADER = ['post_title', 'neighborhood' 'time_of_post', 'description',
                'picture_1', 'picture_2', 'picture_3', 'picture_4',
                'picture_5', 'picture_6', 'picture_7', 'picture_8']
MAX_LENGTH = 500
LOOP_LENGTH_IN_MINUTES = 5
global ERASE_LINE, SHEET_TIME_X, SHEET_TIME_Y_COORDS
ERASE_LINE = '\x1b[2K'
SHEET_TIME_X_COORDS = 2
SHEET_TIME_Y_COORDS = 13


def sendNotification(title, desc, image1=None):
    WEB_HOOKS_URL = 'https://maker.ifttt.com/trigger/{}/with/key/{}'
    access_key = 'oRPAvgcxepSJLJNskGPoaDZBfo5sY4goQIv5QOWLrbe'

    if image1 is None:
        event = 'craigslist_free_no_pic'
        data = {'value1': title, 'value2': desc}
    else:
        event = 'craigslist_free'
        data = {'value1': title, 'value2': desc, 'value3': image1}

    iftt_event_url = WEB_HOOKS_URL.format(event, access_key)

    requests.post(iftt_event_url, json=data)


def openSheet(first_run):
    feeds = "https://spreadsheets.google.com/feeds"
    auth_spreadsheets = 'https://www.googleapis.com/auth/spreadsheets'
    drive_file = "https://www.googleapis.com/auth/drive.file"
    auth_drive = "https://www.googleapis.com/auth/drive"
    scope = [feeds, auth_spreadsheets, drive_file, auth_drive]
    creds = ServiceAccountCredentials.from_json_keyfile_name("creds.json",
                                                             scope)
    if first_run is True:
        print('authorizing...')
    client = gspread.authorize(creds)
    if first_run is True:
        print('opening the worksheet...')
    spreadsheet = client.open("craigslist_free")
    return spreadsheet

# create a class that will hold the properties of an ad


def getMetadata(soup_item):
    # This function is used to get the metadata from a tag and returns the data
    # as a row. My intention is to loop over this function
    worksheet_row = []

    # link to full page craigslist ad
    if soup_item.find(class_='nearby'):
        return

    # Title of the posting
    results = soup_item.find(class_='result-info')
    post_title = results.a.text
    worksheet_row.append(post_title)

    # Neighborhood name
    meta = soup_item.find(class_='result-hood')
    if meta:
        post_hood = meta.text
        post_hood = re.sub(r'[\(\)]', '', post_hood)
        worksheet_row.append(post_hood.strip())
    else:
        worksheet_row.append('')

    # Time of the posting
    time = soup_item.find(class_="result-date")
    exact_time = time.get('title')
    worksheet_row.append(str(exact_time))

    return worksheet_row


def restMetadata(soup_item):
    # ONLY DO THIS FOR EVERY LINE YOU CHECK
    worksheet_row = []
    # link to full page craigslist ad
    post_link = soup_item.a
    post_url = post_link.get('href')

    listing_html = requests.get(post_url)
    listing_soup = BeautifulSoup(listing_html.text, 'html.parser')
    listing_body = listing_soup.find(class_='body')

    # scrape the description of the listing
    description = listing_body.section.section
    for div in description('div'):
        div.decompose()
    description_text = str(description.text).strip('\n')
    description_text = description_text.replace('\n', ' ')
    description_text = re.sub(' +', ' ', description_text)
    if 'show contact info' in description_text:
        description = re.sub('show contact info', '', description)
    worksheet_row.append(description_text)
    # could implement a regex that captures contact info or locations

    # images from the post
    script = listing_body.find("script")
    script_str = str(script)
    script_splt = script_str.split(",")
    image_number = 1
    for text in script_splt:
        if text.startswith('"url"') is True and image_number < 9:
            new_text = text.split(':')
            image_url = str(new_text[1] + ':' + new_text[2]).strip('"')
            worksheet_row.append(image_url)
            image_number += 1
        elif text.startswith('"url"') is False and image_number == 1:
            worksheet_row.append('')

    return worksheet_row


def checkExists(soupItem, sheet, difference=False):
    exists = False  # loop through the result_row
    metadata = getMetadata(soupItem)
    if difference is False:
        if getMetadata(soupItem):
            for row in itertools.islice(sheet.get_all_values(), 0, 6):
                if metadata[0] and metadata[2] in row:
                    exists = True
                    return
            if exists is False:
                return metadata
    else:
        if difference is True:
            if getMetadata(soupItem):
                for row in sheet.get_all_values():
                    if metadata[0] and metadata[2] in row:
                        exists = True
                        return
                if exists is False:
                    return metadata


def insertRow(soupObject, sheet, oldsheet=None):
    num = 2
    if sheet.cell(SHEET_TIME_X_COORDS, SHEET_TIME_Y_COORDS).value == '':
        timeStamp(sheet)

    last_run = sheet.cell(SHEET_TIME_X_COORDS, SHEET_TIME_Y_COORDS).value
    sheet.update_cell(SHEET_TIME_X_COORDS, SHEET_TIME_Y_COORDS, '')
    time_last = time.strptime(last_run, '%a %b %d %H:%M:%S %Y')
    time_last = time.mktime(time_last)
    time_now = time.time()
    difference = (time_now - time_last)
    if difference > (60 * 30):
        print('\nThe last import was more than 30 minutes ago...', end='')
        for index, item in enumerate(soupObject, 0):
            if oldsheet:
                first_half = checkExists(item, oldsheet, True)
            else:
                first_half = checkExists(item, sheet, True)
            if first_half:
                if index == 0:
                    print('\nInserting new data...', end='')

                all_metadata = first_half + restMetadata(item)
                filterAndSend(all_metadata)
                sheet.insert_row(all_metadata, num)
                num = num + 1
            else:
                if index == 0:
                    print('\nNo new posts.', end='')
                break
        sheet.update_cell(SHEET_TIME_X_COORDS,
                          SHEET_TIME_Y_COORDS,
                          last_run)
    else:
        for index, item in itertools.islice(enumerate(soupObject, 0), 0, 5):
            if oldsheet:
                first_half = checkExists(item, oldsheet)
            else:
                first_half = checkExists(item, sheet)
            if first_half:
                if index == 0:
                    print('\nInserting new data...', end='')
                all_metadata = first_half + restMetadata(item)
                filterAndSend(all_metadata)
                sheet.insert_row(all_metadata, num)
                num = num + 1
            else:
                if index == 0:
                    print('\nNo new posts', end='')
                break
        sheet.update_cell(SHEET_TIME_X_COORDS,
                          SHEET_TIME_Y_COORDS,
                          last_run)


def scrapeMain(haveURL=None):
    if haveURL:
        url = haveURL + 'search/zip?'
    else:
        url = "https://{}.craigslist.org/d/free-stuff/search/zip?"
        url = url.format(DESIRED_CITY)

    page = requests.get(url)

    soup = BeautifulSoup(page.text, 'html.parser')

    post = soup.find(class_="rows")
    results = post.find_all(class_='result-row')

    return results


def filterAndSend(fullMetadata):
    title = fullMetadata[0].lower()
    description = fullMetadata[3].lower()
    unwanted_titles = ['soil', 'job', 'iso']  # add more as you see fit
    unwanted_phrases = ['does anyone have', 'does someone have', 'looking for']
    for tag in unwanted_titles:
        if tag in title:
            return
    for tag in unwanted_phrases:
        if tag in description:
            return
    print('\nsending notification to phone...', end='')
    fixed_title = '{} {}'.format(fullMetadata[0], fullMetadata[1])
    sendNotification(fixed_title, fullMetadata[3], fullMetadata[4])


def timeStamp(worksheet=None):
    seconds = time.time()
    new_time = time.ctime(seconds)
    local_time = time.localtime()
    if worksheet:
        worksheet.update_cell(SHEET_TIME_X_COORDS,
                              SHEET_TIME_Y_COORDS,
                              new_time)
    return local_time


def getSecondsUntil(interval_in_minutes):
    current_min = timeStamp().tm_min
    current_sec = timeStamp().tm_sec
    if current_min % interval_in_minutes != 0:
        minutes = 0
        while (current_min + minutes) % interval_in_minutes != 0:
            minutes = minutes + 1
        return ((minutes * 60) - current_sec)
    else:
        return ((interval_in_minutes * 60) - current_sec)


def terminalTimer(totalSec, waitingFor=None):
    if waitingFor is None:
        waitingFor = '.'
    else:
        waitingFor = ' {}'.format(waitingFor)
    for i in range(totalSec, -1, -1):
        minutes = math.floor(i/60)
        seconds = i % 60
        print('\r%d minutes and %d seconds%s'
              % (minutes, seconds, waitingFor), end='', flush=True)
        time.sleep(1)


def main():
    first = True

    while True:
        full_project = openSheet(first)

        # find the name of most recent worksheet
        most_recent = str(full_project.worksheets()[-1].title)

        # grab the number of the most recent worksheet
        sheet_num = int(re.sub('[a-zA-Z\n]', '', most_recent))

        # open the most recent sheet as an object
        worksheet = full_project.worksheet(most_recent)
        if worksheet.cell(SHEET_TIME_X_COORDS,
                          SHEET_TIME_Y_COORDS).value != '':
            last_run = time.strptime(worksheet.cell(SHEET_TIME_X_COORDS,
                                                    SHEET_TIME_Y_COORDS).value,
                                     '%a %b %d %H:%M:%S %Y')
            last_run = time.strftime('%a, %b %d, %I:%M %p %Z', last_run)

            if first is True:
                print('Last Import: {}'.format(last_run), end='')

        for i in range(0, 5):
            result_row = scrapeMain()
            if worksheet.row_values(2):
                if worksheet.row_values(MAX_LENGTH):
                    print('\nfirst worksheet is at maximum' +
                          ',creating a new worksheet...', end='')
                    # create a new worksheet and add the headers
                    sheet_num = sheet_num + 1
                    most_recent = "sheet" + str(sheet_num)
                    full_project.add_worksheet(title=most_recent, rows=505,
                                               cols=len(SHEET_HEADER)+1)
                    old_worksheet = worksheet
                    worksheet = full_project.worksheet(most_recent)
                    worksheet.insert_row(SHEET_HEADER, 1)
                    insertRow(result_row, worksheet, old_worksheet)
                else:
                    insertRow(result_row, worksheet)

            elif not worksheet.row_values(2):
                print('\nempty spreadsheet, filling with data...', end='')
                row_num = 2
                for item in result_row:
                    first_half = getMetadata(item)
                    if first_half:
                        all_metadata = first_half + restMetadata(item)
                        worksheet.insert_row(all_metadata, row_num)
                        row_num = row_num + 1
            else:
                print('\nAn error occured.', end='')
            timeStamp(worksheet)
            timer_length = getSecondsUntil(LOOP_LENGTH_IN_MINUTES)

            if first is True:
                print('\n', end='')
            sys.stdout.write(ERASE_LINE)
            if timer_length == 0:
                terminalTimer(LOOP_LENGTH_IN_MINUTES*60, 'until next attempt.')
            else:
                terminalTimer(timer_length, 'until next attempt.')

            sys.stdout.write(ERASE_LINE)
            print('\rChecking craigslist for new items...\r',
                  end='', flush=True)
            first = False


if __name__ == '__main__':
    main()
