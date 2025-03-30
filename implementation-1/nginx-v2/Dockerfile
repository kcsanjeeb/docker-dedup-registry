FROM ubuntu:latest

RUN apt-get -y update && apt-get -y install nginx && \
	echo "<h1>Nginx v2</h1>" > /var/www/html/index.html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
