from views import bp as views_bp
import os
from flask_cors import CORS
from flask import Flask, request, jsonify
from keras.models import load_model
from keras.preprocessing.image import img_to_array
from google.cloud import speech_v1 as speech
from flask_pymongo import PyMongo
from pydub import AudioSegment
import config  # This imports the config we set up for Google Cloud and MongoDB.
from gpt4_api import call_gpt4_to_extract_info
import cv2
import numpy as np

app = Flask(__name__)

# Load your pre-trained emotion classification model
# Update with the correct path
model_path = '/Users/davidramirez/Desktop/AdaptlyAI/AdaptlyAI/model.h5'
classifier = load_model(model_path)
emotion_labels = ['Angry', 'Disgust', 'Fear','Happy', 'Neutral', 'Sad', 'Surprise']

# Enable CORS for your app

CORS(app)

app.register_blueprint(views_bp)

#cv

@app.route("/detect_emotion", methods=["POST"])
def detect_emotion():
    try:
        # Receive the image data from the client
        image_data = request.files['image'].read()

        # Convert the received data into an OpenCV image
        nparr = np.frombuffer(image_data, np.uint8)
        image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        # Convert the image to grayscale
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        # Detect faces in the grayscale image
        faces = cv2.CascadeClassifier('/Users/davidramirez/Desktop/AdaptlyAI/AdaptlyAI/FLASK-REACT/flask-server/Emotion_Detection/haarcascade_frontalface_default.xml').detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(30, 30),
            flags=cv2.CASCADE_SCALE_IMAGE
        )

        # Check if any faces are detected
        if len(faces) > 0:
            for (x, y, w, h) in faces:
                # Extract the region of interest (ROI) in grayscale
                roi_gray = gray[y:y+h, x:x+w]

                # Resize the ROI to a fixed size (48x48 pixels)
                roi_gray = cv2.resize(roi_gray, (48, 48), interpolation=cv2.INTER_AREA)

                # Normalize the ROI and prepare it for classification
                roi = roi_gray.astype('float') / 255.0
                roi = img_to_array(roi)
                roi = np.expand_dims(roi, axis=0)

                # Make an emotion prediction using the loaded model
                prediction = classifier.predict(roi)[0]

                # Get the emotion label with the highest confidence
                label = emotion_labels[prediction.argmax()]

                # Return the emotion label as a JSON response
                return jsonify({"emotion": label})

        # If no face is detected in the image, return "No Faces" as a JSON response
        return jsonify({"error": "No Faces"})

    except Exception as e:
        return jsonify({"error": str(e)})

# MongoDB Configuration
app.config["MONGO_URI"] = config.MONGO_URI
mongo = PyMongo(app)


def process_audio_file(file_path):
    """Process audio file to ensure it's in mono and 16kHz sample rate."""
    audio = AudioSegment.from_wav(file_path)

    # Convert stereo to mono
    if audio.channels > 1:
        audio = audio.set_channels(1)

    # Set sample rate to 16kHz
    audio = audio.set_frame_rate(16000)

    # Save processed audio
    processed_path = "processed_" + file_path.split("/")[-1]
    audio.export(processed_path, format="wav")

    return processed_path


def speech_to_text(audio_path):
    client = speech.SpeechClient()

    with open(audio_path, 'rb') as f:
        audio_data = f.read()

    audio = speech.RecognitionAudio(content=audio_data)
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        language_code="en-US",
    )

    response = client.recognize(config=config, audio=audio)

    for result in response.results:
        transcript = result.alternatives[0].transcript
        return transcript


@app.route('/speech_to_text', methods=['POST'])
def process_audio():
    if 'file' not in request.files:
        print("No file in request.files")
        return jsonify({'error': 'No file part'}), 400

    file = request.files['file']
    if file.filename == '':
        print("No filename specified")
        return jsonify({'error': 'No selected file'}), 400

    # Saving file temporarily for processing
    audio_path = os.path.join("temporary_storage", file.filename)
    file.save(audio_path)

    # Process the audio to ensure it fits Google STT requirements
    processed_audio_path = process_audio_file(audio_path)

    transcript = speech_to_text(processed_audio_path)
    
    # Extract info from the transcript using GPT-4
    extracted_info = call_gpt4_to_extract_info(transcript)
    
    # Save to MongoDB
    from models import User
    user_id = User.create_user(extracted_info)
    
    os.remove(audio_path)  # Remove the original temporary file after processing
    os.remove(processed_audio_path)  # Remove the processed temporary file after processing
    
    return jsonify({
        'transcript': transcript,
        'extracted_info': extracted_info,
        'user_id': str(user_id.inserted_id)
    })
    
if __name__ == "__main__":
    app.run(debug=True)
