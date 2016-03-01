import argparse
import base64
import json
import requests
from datetime import datetime
from lxml import html
from operator import itemgetter


class ConfluenceBuildVersions(object):
    """
    sudo pip install requests, lxml
    """

    __TEMPLATE_WRAPPER = '<div class="application-versions-table">{paragraph}{table}</div><br></br>'

    __TEMPLATE_APPLICATION_PARAGRAPH = '<p class="application-name">{application_name}</p>'

    __TEMPLATE_TABLE = '<table>' \
                       '<tbody>' \
                       '<tr>' \
                       '<th>Environment</th>' \
                       '<th>Version</th>' \
                       '<th>Commit</th>' \
                       '<th>Build date</th>' \
                       '</tr>' \
                       '{table_rows}' \
                       '</tbody>' \
                       '</table>'

    __TEMPLATE_TABLE_ROW = '<tr class="versions-row">' \
                           '<td class="environment">{environment}</td>' \
                           '<td class="version">{version}</td>' \
                           '<td class="commit">{commit}</td>' \
                           '<td class="timestamp">{timestamp}</td>' \
                           '</tr>'

    __TEMPLATE_COMMIT_URL = '<a class="commit-link" href="https://github.com/comoyo/dpa-gateway/commit/{commit}">{commit}</a>'


    def __init__(self, base_url, page_id, space_id, application_name, environment, application_version, auth, commit='', page_name='Build versions'):
        self.__base_url = base_url
        self.__page_id = page_id
        self.__space_id = space_id
        self.__application_name = application_name
        self.__environment = environment
        self.__application_version = application_version
        self.__auth = ConfluenceBuildVersions.get_auth(auth)
        self.__timestamp = datetime.now().strftime("%d.%m.%Y %H:%M")
        self.__commit = commit
        self.__page_name = page_name
        self.__current_page_version = ''


    @staticmethod
    def get_auth(base64_encoded_auth):
        """
        Get the username and password from a base64 encoded string; base64(username:password)
        :param base64_encoded_auth: the encoded string
        :return: the following tuple: (username, password)
        """
        decode = base64.b64decode(base64_encoded_auth).split(':')
        return decode[0], decode[1]


    def get_current_page_content(self):
        """
        Get the current page contents.
        :return: Page contents in html form
        """
        get_url = '{base}/{rest_path}/{page_id}{expansions}'.format(
            base=self.__base_url,
            rest_path='rest/api/content',
            page_id=self.__page_id,
            expansions='?expand=version,body.storage'
        )
        response = requests.get(url=get_url, auth=self.__auth)
        response.raise_for_status()

        json_response = response.json()
        self.__current_page_version = json_response['version']['number']
        return json_response['body']['storage']['value']


    @staticmethod
    def parse_html_contents(raw_html):
        """
        Parse the html and build a dict from it's contents.
        :param raw_html: the unprocessed contents of the page
        :return: a dict formatted as follows:
        {
            'application_name': {
                'environment': [{
                    'Version': 'version'
                    'Commit': 'commit'
                    'Date': 'timestamp'
                }]
            }
        }
        """
        contents = {}
        if raw_html is None or len(raw_html) == 0:
            return contents

        tree = html.fromstring(raw_html)
        applications = tree.find_class('application-versions-table')

        for application in applications:

            application_name = application.find_class('application-name')[0].text
            rows = application.find_class('versions-row')

            for row in rows:
                environment = row.find_class('environment')[0].text
                timestamp = row.find_class('timestamp')[0].text
                version = row.find_class('version')[0].text

                commit_link = row.find_class('commit')[0].find_class('commit-link')
                if len(commit_link) >= 1 and commit_link[0].text is not None:
                    commit = commit_link[0].text
                else:
                    commit = ''

                ConfluenceBuildVersions.append_content(contents, application_name, environment, version, commit, timestamp)
        return contents


    @staticmethod
    def append_content(current_contents, application_name, environment, version, commit, timestamp):
        """
        Append build information to the current page contents (see parse_html_contents)
        :param current_contents: append to this
        :param application_name: application_name
        :param environment: environment
        :param version: version
        :param commit: commit
        :param timestamp: timestamp
        """
        if application_name in current_contents and environment in current_contents[application_name]:
                current_contents[application_name][environment].append({
                    'Version': version,
                    'Commit': commit,
                    'Date': timestamp
                })
        elif application_name in current_contents:  # New environment
            current_contents[application_name][environment] = [{
                'Version': version,
                'Commit': commit,
                'Date': timestamp
            }]
        else:  # New application
            current_contents[application_name] = {
                environment: [{
                    'Version': version,
                    'Commit': commit,
                    'Date': timestamp
                }]
            }


    def create_new_page_contents(self, current_page_contents):
        """
        Create a html representation of the current page contents and the new build information.
        :param current_page_contents: (see parse_html_contents)
        :return: the html representation in string form
        """
        ConfluenceBuildVersions.append_content(
            current_page_contents,
            self.__application_name,
            self.__environment,
            self.__application_version,
            self.__commit,
            self.__timestamp
        )
        new_page_content = ''

        for application, environment in current_page_contents.iteritems():
            paragraph = self.__TEMPLATE_APPLICATION_PARAGRAPH.format(application_name=application)

            for environment_name, entries in environment.iteritems():

                rows = ''
                entries = sorted(entries, key=itemgetter('Date'), reverse=True)

                for row in entries[:10]:
                    rows += self.__TEMPLATE_TABLE_ROW.format(
                        environment=environment_name,
                        version=row['Version'],
                        commit=self.__TEMPLATE_COMMIT_URL.format(commit=row['Commit']),
                        timestamp=row['Date']
                    )
                table = self.__TEMPLATE_TABLE.format(table_rows=rows)
                new_page_content += self.__TEMPLATE_WRAPPER.format(paragraph=paragraph, table=table)

        return new_page_content


    def update_page(self, new_page_content):
        """
        Update page with new page contents
        :param new_page_content: (see create_new_page_contents)
        """
        data = {
            'id': self.__page_id,
            'type': 'page',
            'space': {
                'key': self.__space_id
            },
            'title': self.__page_name,
            'version': {'number': self.__current_page_version + 1},
            'body': {
                'storage': {
                    'representation': 'storage',
                    'value': new_page_content,
                }
            }
        }
        put_url = '{base}/{rest_path}/{page_id}'.format(
            base=self.__base_url,
            rest_path='rest/api/content',
            page_id=self.__page_id,
        )
        headers = {'Content-Type': 'application/json'}

        response = requests.put(
            url=put_url,
            headers=headers,
            auth=self.__auth,
            data=json.dumps(data)
        )
        response.raise_for_status()


def main():
    parser = argparse.ArgumentParser()
    required_arguments = parser.add_argument_group('required arguments')

    required_arguments.add_argument(
        '--confluence-url',
        required=True,
        help='a confluence base url'
    )

    required_arguments.add_argument(
        '--version',
        required=True,
        help='the new version'
    )

    required_arguments.add_argument(
        '--environment',
        required=True,
        help='the environment'
    )

    required_arguments.add_argument(
        '--auth',
        required=True,
        help='a base64 encoded user-password pair (user:password)'
    )

    required_arguments.add_argument(
        '--application-name',
        required=True,
        help='the application'
    )

    required_arguments.add_argument(
        '--page-id',
        required=True,
        help='the page id'
    )

    required_arguments.add_argument(
        '--space-id',
        required=True,
        help='the confluence space id'
    )

    parser.add_argument(
        '--commit',
        required=False,
        help='the latest commit'
    )

    parser.add_argument(
        '--page-name',
        required=False,
        help='name the page'
    )

    args = parser.parse_args()
    cbv = ConfluenceBuildVersions(
        base_url=args.confluence_url,
        page_id=args.page_id,
        space_id=args.space_id,
        application_name=args.application_name,
        environment=args.environment,
        application_version=args.version,
        commit=args.commit if args.commit is not None else "",
        auth=args.auth
    )
    raw_html_contents = cbv.get_current_page_content()
    current_page_contents = cbv.parse_html_contents(raw_html_contents)
    new_page_content = cbv.create_new_page_contents(current_page_contents)
    cbv.update_page(new_page_content)


if __name__ == '__main__':
    main()
