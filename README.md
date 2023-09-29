# Wikipedia Disambiguation Link Fixer

This Flask web application is designed to help fix disambiguation links in
Wikipedia articles. It makes use of various Python modules, including Flask,
SQLAlchemy, lxml, and Jinja2, to provide a user-friendly interface for editing
and saving changes to Wikipedia articles.

## Features

- Retrieve a list of articles with disambiguation links from
  [dplbot.toolforge.org](https://dplbot.toolforge.org/articles_with_dab_links.php).
- Edit Wikipedia articles directly within the app.
- Automatically generate edit summaries for your changes.
- OAuth integration for secure Wikipedia authentication.

## Prerequisites

Before you can run this application, ensure you have the following prerequisites
installed:

- Python 3.x
- Flask
- SQLAlchemy
- lxml
- Jinja2
- requests
- requests-oauthlib

You'll also need to obtain OAuth credentials from Wikipedia to use the
authentication features.

## Installation

1. Clone this repository to your local machine:

   ```
   git clone https://git.4angle.com/edward/dab-mechanic.git
   ```

2. Navigate to the project directory:

   ```
   cd dab-mechanic
   ```

3. Install the required Python packages using pip:

   ```
   pip install -r requirements.txt
   ```

4. Configure the application by modifying the `config.default` file with your
   OAuth credentials and other settings.

## Usage

1. Start the Flask application:

   ```
   python3 web_view.py
   ```

2. Access the app in your web browser at `http://localhost:5000`.

3. Log in with your Wikipedia account using OAuth.

4. Browse the list of articles with disambiguation links and make necessary
   edits.

5. Save your edits, and the application will update the Wikipedia articles
   accordingly.

## Contributing

Contributions are welcome! If you'd like to improve this application or report
issues, please create a pull request or open an issue on the [Forgejo
repository](https://git.4angle.com/edward/dab-mechanic).

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file
for details.

## Acknowledgments

- This application was developed by Edward Betts.

## Contact

If you have any questions or need assistance,
you can contact Edward Betts at edward@4angle.com
