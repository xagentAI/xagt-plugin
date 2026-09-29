#!/bin/sh
set -eu

cert_name='bountyproof.89-58-17-36.sslip.io'
site_ssl="/opt/1panel/www/sites/${cert_name}/ssl"
renewed_domains=${RENEWED_DOMAINS:-$cert_name}
renewed_lineage=${RENEWED_LINEAGE:-/etc/letsencrypt/live/$cert_name}

case " $renewed_domains " in
    *" $cert_name "*) ;;
    *) exit 0 ;;
esac

/usr/bin/install -d -m 700 "$site_ssl"
/usr/bin/install -m 644 "$renewed_lineage/fullchain.pem" "$site_ssl/fullchain.pem"
/usr/bin/install -m 600 "$renewed_lineage/privkey.pem" "$site_ssl/privkey.pem"
/usr/bin/docker exec 1Panel-openresty-yzF9 openresty -t
/usr/bin/docker exec 1Panel-openresty-yzF9 openresty -s reload
