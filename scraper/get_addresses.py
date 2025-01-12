from bs4 import BeautifulSoup
import requests
from w3lib.html import remove_tags
import csv
import time

def get_schools(soup):
    selector = "h3 > a"
    school_pages = soup.select(selector)
    schools = [remove_tags(str(school)) for school in school_pages]
    res = []
    for tag in school_pages:
        res.append(tag['href'])
    return res

def check_status(base,school_page):
    session = requests.session()
    for_cookies = session.get("https://reports.ofsted.gov.uk/")
    cookies = for_cookies.cookies
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; Win64; x64; rv:57.0) Gecko/20100101 Firefox/57.0'}
    my_url = base+school_page
    response = session.get(my_url,headers=headers,cookies=cookies)
    return int(response.status_code)

def get_school_data(base,school_page,status,csv_writer):
    activity_page = requests.get(base+school_page)
    soup = BeautifulSoup(activity_page.text, 'html.parser')
    school_name_selector = soup.select("h1", class_="heading--title")
    row = []
    if school_name_selector:
        school_name = school_name_selector[0].text
        row.append(school_name)
    else:
        print ("Error: school name not found. Skipping school: {}".format(school_page))
        return

    status = check_status(base,school_page)
    if status != 200:
        with open("retry_addresses.txt", "a") as txt_file:
            my_url = base+school_page
            txt_file.write(my_url)
            txt_file.close()
            print ("Error: request returned {} status".format(status))
        return

    address = soup.select("address")
    if address:
        address = address[0].text
    else:
        print ("address not found")
        address = ""
    row.append(address)
    # info = soup.select("ul", class_="info-block__items list-unstyled")[0].select("span")
    # info_strings = [remove_tags(str(i)) for i in info if i]
    # if info_strings:
    #     info_strings[1::2] # Type, religious character, local authority, region, telephone
    #     row.extend(info_strings)
    csv_writer.writerow(row)

def get_next_page(soup):
    next_page = [tag for tag in soup.find_all('a') if tag.get("class") == "pagination__next"]
    next_page = soup.find_all('a', {'class': 'pagination__next'})
    if next_page:
        return next_page[0]['href']

def main():
    open_path = "/search?q=&location=&radius=3&status%5B0%5D=1&start=42500&rows=10"
    closed = "/search?q=&location=&radius=3&status%5B0%5D=2&start=52000&rows=10"
    urls = [open_path,closed]
    count = 0
    base = "https://reports.ofsted.gov.uk"
    with open("school_addresses.csv", "w") as f:
        csv_writer = csv.writer(f, delimiter=',')
        csv_writer.writerow(['school','address'])
        for url in urls:
            next = True
            while next:
                if count == 0:
                    status = "open"
                else:
                    status = "closed"
                page = requests.get(base+url)
                soup = BeautifulSoup(page.text, 'html.parser')
                if soup.find_all("h1")[0].text == "Slim Application Error":
                    continue # retry the url in case an application error occurs
                schools = get_schools(soup)
                for school in schools:
                    get_school_data(base,school,status,csv_writer)
                    time.sleep(0.2)
                next_page = get_next_page(soup)
                if next_page:
                    url = next_page
                else:
                    count += 1
                    next = False

main()
