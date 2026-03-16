import smtplib

try:
    server = smtplib.SMTP('smtp.office365.com', 587)
    server.ehlo()
    server.starttls()
    server.ehlo()
    server.login('noreply@getveloce.com', 'L(927435524607og')
    print("✅ SMTP Login Successful!")
    server.quit()
except Exception as e:
    print(f"❌ Error: {e}")