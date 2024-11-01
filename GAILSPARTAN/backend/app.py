from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message
import random
import openai
from io import StringIO
from pdfminer.pdfinterp import PDFResourceManager, PDFPageInterpreter
from pdfminer.converter import TextConverter
from pdfminer.layout import LAParams
from pdfminer.pdfpage import PDFPage

# This is a simple flask application 

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key'  # Replace with a strong secret key
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///chatbot.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Email configuration
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'your_email@gmail.com'
app.config['MAIL_PASSWORD'] = 'your_email_password'
mail = Mail(app)

# OpenAI API key
openai.api_key = 'your_openai_api_key'

# Gemini api key
GEMINI_API_KEY  = 'your_gemini_api_key'

#SerpAPI Key
SERPAPI_API_KEY = 'your_serpapi_key'

# Database models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    verification_code = db.Column(db.String(6), nullable=True)

# This for keeping the record of the old chats as openai and gemini Do 

class ChatHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.Text, nullable=False)
    response = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=db.func.current_timestamp(), nullable=False)

db.create_all()

# PDF text extraction function
def extract_text_from_pdf(pdf_file):
    resource_manager = PDFResourceManager()
    ret_str = StringIO()
    laparams = LAParams()
    device = TextConverter(resource_manager, ret_str, laparams=laparams)
    interpreter = PDFPageInterpreter(resource_manager, device)

    for page in PDFPage.get_pages(pdf_file):
        interpreter.process_page(page)

    text = ret_str.getvalue()
    device.close()
    ret_str.close()
    return text

# Routes
@app.route('/')
def home():
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = generate_password_hash(request.form['password'])
        email = request.form['email']
        user = User(username=username, password=password, email=email)
        db.session.add(user)
        db.session.commit()
        return redirect(url_for('login'))
    return render_template('register.html')

# This set of codes is for api working or you can say routes
@app.route('/search', methods=['GET'])
def search():
    query = request.args.get('query')
    url = f"https://serpapi.com/search?q={query}&api_key={SERPAPI_KEY}"
    response = requests.get(url)
    return jsonify(response.json())

@app.route('/gemini', methods=['POST'])
def gemini():
    data = request.json
    headers = {
        'Authorization': f'Bearer {GEMINI_API_KEY}',
        'Content-Type': 'application/json'
    }
    response = requests.post('https://api.gemini.com/v1/some_endpoint', headers=headers, json=data)
    return jsonify(response.json())

@app.route('/openai', methods=['POST'])
def openai_api():
    prompt = request.json.get('prompt')
    response = openai.Completion.create(
        engine="davinci-codex",
        prompt=prompt,
        max_tokens=100
    )
    return jsonify(response.choices[0].text)


# This is for the  login functionality
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['username'] = user.username
            # Generate and send verification code
            verification_code = str(random.randint(100000, 999999))
            user.verification_code = verification_code
            db.session.commit()
            send_verification_email(user.email, verification_code)
            return redirect(url_for('verify'))
        return 'Invalid username or password'
    return render_template('login.html')

@app.route('/verify', methods=['GET', 'POST'])
def verify():
    if request.method == 'POST':
        code = request.form['code']
        user = User.query.get(session['user_id'])
        if user and user.verification_code == code:
            user.verification_code = None
            db.session.commit()
            return redirect(url_for('chat'))
        return 'Invalid verification code'
    return render_template('verify.html')

@app.route('/chat', methods=['GET', 'POST'])
def chat():
    if 'username' not in session:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        user_message = request.form['message']
        user_id = session['user_id']

        # Check if a PDF file was uploaded
        if 'pdf_file' in request.files:
            pdf_file = request.files['pdf_file']
            if pdf_file.filename != '':
                pdf_text = extract_text_from_pdf(pdf_file)
                user_message += f"\n\nExtracted PDF content:\n{pdf_text}"

        response = generate_response(user_message)

        # Save chat history
        chat_history = ChatHistory(user_id=user_id, message=user_message, response=response)
        db.session.add(chat_history)
        db.session.commit()

        return jsonify({'response': response})

    return render_template('chat.html')

@app.route('/get_chat_history')
def get_chat_history():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    user_id = session['user_id']
    history = ChatHistory.query.filter_by(user_id=user_id).order_by(ChatHistory.timestamp.desc()).limit(10).all()
    history_list = [{'message': h.message, 'response': h.response, 'timestamp': h.timestamp.isoformat()} for h in history]
    return jsonify(history_list)

def generate_response(message):
    response = openai.Completion.create(
        model="text-davinci-003",
        prompt=message,
        max_tokens=150
    )
    return response.choices[0].text.strip()

def send_verification_email(email, code):
    msg = Message('Your Verification Code', sender='noreply@example.com', recipients=[email])
    msg.body = f'Your verification code is {code}'
    mail.send(msg)

if __name__ == '__main__':
    app.run(debug=True)