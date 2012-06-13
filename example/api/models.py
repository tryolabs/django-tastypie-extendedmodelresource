from django.contrib.auth.models import User
from django.db import models
from django.template.defaultfilters import slugify
from django.utils.timezone import now


class Entry(models.Model):
    user = models.ForeignKey(User, related_name='entries')
    pub_date = models.DateTimeField(default=now)
    title = models.CharField(max_length=200)
    slug = models.SlugField()
    body = models.TextField()
    entryinfo = models.ForeignKey('EntryInfo', null=True, blank=True,
                                  related_name='entry')

    def __unicode__(self):
        return self.title

    def save(self, *args, **kwargs):
        # For automatic slug generation.
        if not self.slug:
            self.slug = slugify(self.title)[:50]

        return super(Entry, self).save(*args, **kwargs)


class EntryInfo(models.Model):
    somefield = models.CharField(max_length=200)
