from flask import Flask, request

app = Flask(__name__)

@app.route('/location')
def location():
    lat = request.args.get('lat')
    lon = request.args.get('lon')

    print(f"?? GPS received -> Latitude: {lat}, Longitude: {lon}")
    return "OK"

app.run(host='0.0.0.0', port=5000)
